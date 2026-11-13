"""The scanner of the shell reader (shell.py): a line split into commands the way bash, PowerShell or cmd splits it,
before any wrapper is taken off. Unread is raised for what it cannot see whole; it never runs the text."""
import re
from dataclasses import dataclass, field

NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
BASH_REDIRECTS = (">>", ">|", ">&", "<<<", "<<-", "<<", "<&", "<>", ">", "<")
OTHER_REDIRECTS = (">>", ">&", ">", "<")
HEREDOCS = ("<<", "<<-")


class Unread(Exception):
    """The line cannot be seen whole; the message says why."""


@dataclass(frozen=True)
class Word:
    text: str
    dynamic: bool = False


@dataclass
class Command:
    words: list = field(default_factory=list)
    env: list = field(default_factory=list)
    redirects: list = field(default_factory=list)
    heredoc: str = None
    dialect: str = "bash"
    via: tuple = ()
    stdin_args: bool = False

    @property
    def name(self):
        return self.words[0].text if self.words else ""

    @property
    def args(self):
        return self.words[1:]


class Scanner:
    def __init__(self, text, dialect):
        self.t, self.d, self.i = text, dialect, 0
        self.commands, self.tokens, self.cur = [], [], Command(dialect=dialect)
        self.buf, self.dyn, self.quoted, self.assign = None, False, False, False
        self.redir, self.heredocs = None, []

    def run(self):
        step = {"bash": self.bash, "powershell": self.powershell, "cmd": self.cmd}[self.d]
        while self.i < len(self.t):
            step(self.t[self.i])
        self.end_command()
        if self.heredocs:
            raise Unread("a heredoc with no body")
        return self.commands

    # words and commands
    def add(self, text, dynamic=False):
        if self.buf is None:
            self.buf = []
        self.buf.append(text)
        self.dyn = self.dyn or dynamic

    def end_word(self):
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

    def end_command(self):
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

    def newline(self):
        self.i += 1
        self.end_command()
        for command, end, strip, expands in self.heredocs:
            command.heredoc = self.body(end, strip, expands)
        self.heredocs = []

    def body(self, end, strip, expands):
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

    def redirect(self, ops, fd_marks="0123456789"):
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

    def separator(self, double_ends=("&&", "||", "|&"), single="", unread_single=""):
        two = self.t[self.i:self.i + 2]
        if two in double_ends:
            self.i += 2
        elif self.t[self.i] in unread_single:
            raise Unread(f"{self.t[self.i]} here runs a command or a job the reader does not follow")
        else:
            self.i += 1
        self.end_command()

    def comment(self):
        nl = self.t.find("\n", self.i)
        self.i = len(self.t) if nl < 0 else nl

    def single_quotes(self, doubled):
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
    def bash(self, c):
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

    def tokens_have_command(self):
        return any(not assign for _, assign in self.tokens)

    def bash_double(self):
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

    def powershell(self, c):
        t, i = self.t, self.i
        if c in " \t\r":
            self.end_word()
            self.i += 1
        elif c == "\n":
            self.i += 1
            self.end_command()
        elif c == "`":
            raise Unread("a PowerShell backtick escape")
        elif c == "'":
            self.single_quotes(doubled=True)
        elif c == '"':
            self.powershell_double()
        elif c == "$":
            if t.startswith("$(", i):
                raise Unread("$( ) runs a command inside the line")
            self.add("$", True)
            self.i += 1
        elif c == "@" and self.buf is None and t[i + 1:i + 2] in ("(", "{", "'", '"'):
            raise Unread("@( ), @{ } or a here-string")
        elif c == "#" and self.buf is None:
            self.comment()
        elif c in "(){}":
            raise Unread(f"{c} opens an expression or a script block")
        elif c in ";|&":
            self.separator(double_ends=("&&", "||"), unread_single="&")
        elif c == ">":
            self.redirect(OTHER_REDIRECTS, fd_marks="0123456789*")
        elif c == "<":
            raise Unread("< in PowerShell")
        else:
            self.add(c, c in "*?[," or (c == "~" and self.buf is None))
            self.i += 1

    def powershell_double(self):
        t, j, out = self.t, self.i + 1, []
        while True:
            if j >= len(t):
                raise Unread("a quote is left open")
            if t[j] == '"':
                if t.startswith('""', j):
                    out.append('"')
                    j += 2
                    continue
                break
            if t.startswith("$(", j) or t[j] == "`":
                raise Unread("a command or an escape inside a double-quoted word")
            self.dyn = self.dyn or t[j] == "$"
            out.append(t[j])
            j += 1
        self.add("".join(out))
        self.quoted, self.i = True, j + 1

    def cmd(self, c):
        t = self.t
        if c in " \t\r":
            self.end_word()
            self.i += 1
        elif c == "\n":
            self.i += 1
            self.end_command()
        elif c == "^":
            raise Unread("a cmd escape ^")
        elif c in "()":
            raise Unread("( ) opens a cmd block")
        elif c == '"':
            k = t.find('"', self.i + 1)
            if k < 0:
                raise Unread("a quote is left open")
            part = t[self.i + 1:k]
            self.add(part, "%" in part or "!" in part)
            self.quoted, self.i = True, k + 1
        elif c in "&|":
            self.separator(double_ends=("&&", "||"))
        elif c in "<>":
            self.redirect(OTHER_REDIRECTS)
        else:
            self.add(c, c in "%!*?")
            self.i += 1


def scan(text, dialect="bash"):
    """The commands of a line as written, wrappers not taken off yet."""
    return Scanner(str(text), dialect).run()
