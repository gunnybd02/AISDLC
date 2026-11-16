"""The PowerShell and cmd readers of the shell scanner (scan.py): OtherDialects holds the character readers of those
two dialects, and Scanner takes them in. They use the scanner's own state and steps (t, i, buf, add, end_word,
end_command, separator, redirect, single_quotes, comment), so they run only as methods of a Scanner."""
from __future__ import annotations

from harness.utils.shell.command import Unread

OTHER_REDIRECTS = (">>", ">&", ">", "<")


class OtherDialects:
    """The character readers of PowerShell and cmd lines, a part of Scanner."""

    def powershell(self, c: str) -> None:
        """Read the next character of a PowerShell line.

        Args:
            c: the character at self.i.

        Raises:
            Unread: a backtick escape, $( ), @( ), @{ }, a here-string, an expression or a script block, & or <.
        """
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

    def powershell_double(self) -> None:
        """Read a double-quoted part of a PowerShell word; "" stands for one quote, a $ inside makes it dynamic.

        Raises:
            Unread: a command or an escape inside it, or the quote left open.
        """
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

    def cmd(self, c: str) -> None:
        """Read the next character of a cmd line.

        Args:
            c: the character at self.i.

        Raises:
            Unread: a ^ escape, a ( ) block, or an open quote.
        """
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
