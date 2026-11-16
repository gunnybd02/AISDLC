"""The commit the harness makes for a plan: only the paths given, whatever else the index holds. `git add` stages them
(a deletion too), `git commit --only` records exactly them; the repository's own hooks run as for any commit."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from harness.utils.git.run import git


def changed(repo: str | Path, paths: Sequence[str]) -> list[str]:
    """The paths (from the repository root) whose working tree differs from HEAD: changed, new or deleted.

    Args:
        repo: the repository.
        paths: the paths to look at (pathspecs for git status).

    Returns:
        The changed paths, sorted.

    Raises:
        GitError: git status fails.
    """
    out = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames", "--", *paths)
    return sorted({entry[3:] for entry in out.split("\0") if len(entry) > 3})


def commit(repo: str | Path, paths: Sequence[str], message: str) -> str:
    """Commit exactly paths with message; the new HEAD.

    Args:
        repo: the repository.
        paths: the paths to stage and commit (a deletion too, one already staged with git rm as well: only the
            paths still in the tree or the index are staged, git refuses the others, and the commit takes them all).
        message: the commit message.

    Returns:
        The sha of the new HEAD.

    Raises:
        GitError: git add, git commit (a hook too) or git rev-parse fails.
    """
    tracked = set(git(repo, "ls-files", "-z", "--", *paths).split("\0")) if paths else set()
    known = [p for p in paths if (Path(repo) / p).exists() or p in tracked]  # a staged deletion is in neither
    if known:
        git(repo, "add", "--all", "--", *known)
    git(repo, "commit", "--only", "-q", "-m", message, "--", *paths)
    return git(repo, "rev-parse", "HEAD").strip()
