"""Paths a command names: a target word, an absolute path from a cwd (on Windows, a Git Bash /c/ drive read as C:/), and Unseen,
raised when the reader cannot tell what a command touches."""
import os
import re
from dataclasses import dataclass

from harness.utils.shell.scan import Word


class Unseen(Exception):
    """A command whose writes the tables cannot tell; the message says why."""


@dataclass(frozen=True)
class Target:
    """A place a command writes; names: when the place is a folder, the files written inside it (a copy, a move)."""
    word: Word
    names: tuple = ()


def absolute(path, cwd, dialect=None):
    drive = re.match(r"^/([a-zA-Z])(/|$)", path) if dialect == "bash" and os.name == "nt" else None  # Git Bash
    if drive:
        path = f"{drive.group(1).upper()}:/{path[drive.end():]}"
    return os.path.normpath(os.path.join(cwd or os.getcwd(), path)).replace("\\", "/")
