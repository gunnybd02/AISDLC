"""Branches: which ones are protected (names or patterns, fnmatch: main, release/*), and the branch a repository is on."""
from __future__ import annotations

from collections.abc import Iterable
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Optional

from harness.utils.git.run import GitError, git

DEFAULT_PROTECTED = ("main", "master")


def is_protected(branch: Optional[str], patterns: Iterable[str]) -> bool:
    """Whether a branch is protected.

    Args:
        branch: the branch's name, with or without refs/heads/; None or "" is no branch.
        patterns: the protected names or fnmatch patterns (main, release/*).

    Returns:
        True when the name matches a pattern (case kept).
    """
    name = str(branch or "").removeprefix("refs/heads/")
    return bool(name) and any(fnmatchcase(name, p) for p in patterns)


def current(repo: str | Path) -> str:
    """The branch the repository is on, or "" (detached, or no repository).

    Args:
        repo: a folder of the repository.

    Returns:
        The short branch name, or "".
    """
    try:
        return git(repo, "symbolic-ref", "--short", "-q", "HEAD").strip()
    except GitError:
        return ""
