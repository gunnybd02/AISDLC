"""The scanner of the shell reader (shell.py): a line split into commands the way bash, PowerShell or cmd splits it,
before any wrapper is taken off. Unread is raised for what it cannot see whole; it never runs the text."""
from __future__ import annotations

import re

from harness.utils.shell.command import Command, Unread, Word
from harness.utils.shell.dialects import OtherDialects

NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
BASH_REDIRECTS = (">>", ">|", ">&", "<<<", "<<-", "<<", "<&", "<>", ">", "<")
HEREDOCS = ("<<", "<<-")


class Scanner(OtherDialects):
    """Reads one line character by character in its dialect and gives its commands; Unread for what it cannot see.
    The PowerShell and cmd readers come from OtherDialects (dialects.py)."""

    def __init__(self, text: str, dialect: str) -> None:
        """Start at the line's first character.

        Args:
            text: the line.
            dialect: "bash", "powershell" or "cmd".
        """
        self.t, self.d, self.i = text, dialect, 0
        self.commands, self.tokens, self.cur = [], [], Command(dialect=dialect)
        self.buf, self.dyn, self.quoted, self.assign = None, False, False, False
        self.redir, self.heredocs = None, []

    def run(self) -> list[Command]:
        """Read the whole line.

        Returns:
            Its commands as written, each with its heredoc's body.

        Raises:
            Unread: the line cannot be seen whole.
        """
        step = {"bash": self.bash, "powershell": self.powershell, "cmd": self.cmd}[self.d]
        while self.i < len(self.t):
            step(self.t[self.i])
        self.end_command()
        if self.heredocs:
            raise Unread("a heredoc with no body")
        return self.commands

    # words and commands
    def add(self, text: str, dynamic: bool = False) -> None:
        """Add text to the word being read.

        Args:
            text: the characters, quotes and escapes taken off.
            dynamic: True when the shell makes them when it runs.
        """
        if self.buf is None:
            self.buf = []
        self.buf.append(text)
        self.dyn = self.dyn or dynamic

    def end_word(self) -> None:
        """End the word being read: a heredoc's end word, a redirection's target, or a word of the command.

        Raises:
            Unread: a PowerShell --% outside quotes.
        """
        if self.buf is None:
            return
        word = Word("".join(self.buf), self.dyn)
        if word.text == "--%" and not self.quoted and self.d == "powershell":
            raise Unread("--% stops PowerShell from parsing the rest")
        if self.redir in HEREDOCS and self.d == "bash":
            self.heredocs.append((self.cur, word.text, self.redir == "<<-", not self.quoted))
        elif self.redir:
            self.cur.redirects.append((self.redir, word))
        else:
            self.tokens.append((word, self.assign))
        self.buf, self.dyn, self.quoted, self.assign, self.redir = None, False, False, False, None

    def end_command(self) -> None:
        """End the command being read: its leading NAME=value words (bash) become its env; keep it unless empty.

        Raises:
            Unread: a redirection has no target.
        """
        self.end_word()
        if self.redir:
            raise Unread(f"the redirection {self.redir} has no target")
        n = 0
        while n < len(self.tokens) and self.tokens[n][1] and self.d == "bash":
            n += 1
        self.cur.env = [w.text for w, _ in self.tokens[:n]]
        self.cur.words = [w for w, _ in self.tokens[n:]]
        if self.cur.words or self.cur.env or self.cur.redirects or any(h[0] is self.cur for h in self.heredocs):
            self.commands.append(self.cur)
        self.tokens, self.cur = [], Command(dialect=self.d)

    def newline(self) -> None:
        """Pass a newline: end the command, then read the bodies of the heredocs it opened."""
        self.i += 1
        self.end_command()
        for command, end, strip, expands in self.heredocs:
            command.heredoc = self.body(end, strip, expands)
        self.heredocs = []

    def body(self, end: str, strip: bool, expands: bool) -> str:
        """Read a heredoc's body from the line after its command, up to its end line.

        Args:
            end: the end word.
            strip: True for <<-: leading tabs are taken off each line.
            expands: True when the end word was not quoted: the shell expands the body.

        Returns:
            The body's lines, each ended by a newline.

        Raises:
            Unread: no end line, or an expanding body runs a command ($( ) or a backtick).
        """
        lines, pos = [], self.i
        while pos <= len(self.t):
            nl = self.t.find("\n", pos)
            stop = len(self.t) if nl < 0 else nl
            line = self.t[pos:stop].rstrip("\r")
            line = line.lstrip("\t") if strip else line
            if line == end:
                self.i = stop + 1
                text = "".join(f"{x}\n" for x in lines)
                if expands and ("$(" in text or "`" in text):
                    raise Unread("a heredoc whose body runs a command ($( ) or a backtick)")
                return text
            if nl < 0:
                break
            lines.append(line)
            pos = nl + 1
        raise Unread(f"a heredoc with no end line {end}")

    def redirect(self, ops: tuple[str, ...], fd_marks: str = "0123456789") -> None:
        """Read a redirection operator; its target is the next word (a file descriptor before it is dropped).

        Args:
            ops: the operators of the dialect, longest first.
            fd_marks: the characters of a file descriptor written before the operator.

        Raises:
            Unread: the redirection before has no target, or a process substitution <( ) or >( ).
        """
        if self.buf is not None and not self.quoted and self.buf and all(c in fd_marks for c in "".join(self.buf)):
            self.buf, self.dyn = None, False  # the file descriptor before the operator
        self.end_word()
        if self.redir:
            raise Unread(f"the redirection {self.redir} has no target")
        op = next(o for o in ops if self.t.startswith(o, self.i))
        self.i += len(op)
        if op in ("<", ">") and self.t.startswith("(", self.i):
            raise Unread("a process substitution <( ) or >( ) runs a command inside the line")
        self.redir = op

    def separator(self, double_ends: tuple[str, ...] = ("&&", "||", "|&"), single: str = "",
                  unread_single: str = "") -> None:
        """Read a separator between commands (; & | && ||...) and end the command.

        Args:
            double_ends: the two-character separators of the dialect.
            single: not read.
            unread_single: single characters the reader does not follow here (PowerShell's &).

        Raises:
            Unread: a character of unread_single.
        """
        two = self.t[self.i:self.i + 2]
        if two in double_ends:
            self.i += 2
        elif self.t[self.i] in unread_single:
            raise Unread(f"{self.t[self.i]} here runs a command or a job the reader does not follow")
        else:
            self.i += 1
        self.end_command()

    def comment(self) -> None:
        """Skip a comment up to the end of its line."""
        nl = self.t.find("\n", self.i)
        self.i = len(self.t) if nl < 0 else nl

    def single_quotes(self, doubled: bool) -> None:
        """Read a single-quoted part of a word: no escape inside.

        Args:
            doubled: True in PowerShell, where '' inside stands for one quote.

        Raises:
            Unread: the quote is left open.
        """
        j = self.i + 1
        out = []
        while True:
            k = self.t.find("'", j)
            if k < 0:
                raise Unread("a quote is left open")
            out.append(self.t[j:k])
            if doubled and self.t.startswith("''", k):
                out.append("'")
                j = k + 2
                continue
            self.i = k + 1
            break
        self.add("".join(out))
        self.quoted = True

    # dialects
    def bash(self, c: str) -> None:
        """Read the next character of a bash line.

        Args:
            c: the character at self.i.

        Raises:
            Unread: a command run inside the line, a subshell or a group, $' or $", a case, an open quote...
        """
        t, i = self.t, self.i
        if c in " \t\r":
            self.end_word()
            self.i += 1
        elif c == "\n":
            self.newline()
        elif c == "\\":
            if i + 1 >= len(t):
                raise Unread("a backslash ends the line")
            if t[i + 1] != "\n":
                self.add(t[i + 1])
                self.quoted = True
            self.i += 2
        elif c == "'":
            self.single_quotes(doubled=False)
        elif c == '"':
            self.bash_double()
        elif c == "$":
            if t.startswith(("$(", "$'", '$"'), i):
                raise Unread(f"{t[i:i + 2]} runs a command or quotes in a way the reader does not follow")
            self.add("$", True)
            self.i += 1
        elif c == "`":
            raise Unread("a backtick runs a command inside the line")
        elif c == "#" and self.buf is None:
            self.comment()
        elif c in "()":
            raise Unread("( ) opens a subshell or a group")
        elif c in "{}" and self.buf is None and (i + 1 >= len(t) or t[i + 1] in " \t\r\n;"):
            raise Unread("{ } opens a group")
        elif c in ";&|":
            if t.startswith(";;", i):
                raise Unread(";; belongs to a case the reader does not follow")
            if t.startswith("&>", i):
                self.redirect(("&>>", "&>"))
            else:
                self.separator()
        elif c in "<>":
            self.redirect(BASH_REDIRECTS)
        else:
            if c == "=" and self.buf is not None and not self.quoted and not self.tokens_have_command() \
                    and NAME.match("".join(self.buf)):
                self.assign = True
            self.add(c, c in "*?[{}" or (c == "~" and self.buf is None))
            self.i += 1

    def tokens_have_command(self) -> bool:
        """Whether the command being read has a word that is no NAME=value assignment.

        Returns:
            True once its command word was read.
        """
        return any(not assign for _, assign in self.tokens)

    def bash_double(self) -> None:
        """Read a double-quoted part of a bash word; a $ inside makes it dynamic.

        Raises:
            Unread: a command run inside it, or the quote left open.
        """
        t, j, out = self.t, self.i + 1, []
        while j < len(t) and t[j] != '"':
            if t[j] == "\\" and j + 1 < len(t) and t[j + 1] in '$`"\\\n':
                out.append("" if t[j + 1] == "\n" else t[j + 1])
                j += 2
                continue
            if t.startswith("$(", j) or t[j] == "`":
                raise Unread("a command runs inside a double-quoted word")
            self.dyn = self.dyn or t[j] == "$"
            out.append(t[j])
            j += 1
        if j >= len(t):
            raise Unread("a quote is left open")
        self.add("".join(out))
        self.quoted, self.i = True, j + 1


def scan(text: str, dialect: str = "bash") -> list[Command]:
    """The commands of a line as written, wrappers not taken off yet.

    Args:
        text: the line (any value is made a string).
        dialect: "bash", "powershell" or "cmd".

    Returns:
        The commands in order.

    Raises:
        Unread: the line cannot be seen whole.
    """
    return Scanner(str(text), dialect).run()
