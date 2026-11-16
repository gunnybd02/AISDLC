"""Paths a command names: a target word, an absolute path from a cwd (on Windows, a Git Bash /c/ drive read as C:/), and Unseen,
raised when the reader cannot tell what a command touches."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

from harness.utils.shell.command import Word


class Unseen(Exception):
    """A command whose writes the tables cannot tell; the message says why."""


@dataclass(frozen=True)
class Target:
    """A place a command writes; names: when the place is a folder, the files written inside it (a copy, a move)."""
    word: Word
    names: tuple[str, ...] = ()


def absolute(path: str, cwd: Optional[str], dialect: Optional[str] = None) -> str:
    """A path a command names, made absolute from its folder.

    Args:
        path: the path as written.
        cwd: the folder the command runs in; None or "" for the process's own.
        dialect: the line's dialect; on Windows a bash /c/... path is read as C:/...

    Returns:
        The absolute normalised path with forward slashes.
    """
    drive = re.match(r"^/([a-zA-Z])(/|$)", path) if dialect == "bash" and os.name == "nt" else None  # Git Bash
    if drive:
        path = f"{drive.group(1).upper()}:/{path[drive.end():]}"
    return os.path.normpath(os.path.join(cwd or os.getcwd(), path)).replace("\\", "/")
