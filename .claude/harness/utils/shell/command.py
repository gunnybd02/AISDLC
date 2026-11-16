"""What the shell reader passes around: a Word, a Command (scan.py makes them, words.py takes their wrappers off), and
Unread, raised for a line the reader cannot see whole."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class Unread(Exception):
    """The line cannot be seen whole; the message says why."""


@dataclass(frozen=True)
class Word:
    """One word of a command as the shell gives it (quotes and escapes taken off); dynamic when the shell makes its
    value when it runs (a variable, a glob, ~, a brace)."""
    text: str
    dynamic: bool = False


@dataclass
class Command:
    """One command of a line: its words, the NAME=value assignments before it, its redirections [(op, Word)], its
    heredoc's body, its dialect, the wrappers taken off it (via, outermost first) and whether xargs gives it words."""
    words: list[Word] = field(default_factory=list)
    env: list[str] = field(default_factory=list)
    redirects: list[tuple[str, Word]] = field(default_factory=list)
    heredoc: Optional[str] = None
    dialect: str = "bash"
    via: tuple[str, ...] = ()
    stdin_args: bool = False

    @property
    def name(self) -> str:
        """The text of the first word, "" when there is none."""
        return self.words[0].text if self.words else ""

    @property
    def args(self) -> list[Word]:
        """The words after the first."""
        return self.words[1:]
