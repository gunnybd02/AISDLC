"""The check after (auto mode): a shell command the reader cannot see whole runs without asking the user, and the
harness judges what it changed instead. Before it runs, the harness keeps a snapshot of its repository: each changed or
untracked file with the hash of its content. After it ran, a new snapshot; a file dirty now whose content the first
snapshot did not hold is a write of the command (gear/translate/planfiles.py judges it against the plan). A file the
command restored clean, or left as it was, is no write. Ignored files and files outside the repository are not seen."""
from __future__ import annotations

import os
from typing import Optional

from harness.utils.git.run import GitError, git
from harness.utils.ledger.writes import content_hash

Snapshot = dict[str, str]  # {path from the top of the repository: content hash, "" for a file that is gone}
MOST = 5000  # changed files a snapshot hashes at most: a tree more changed than this is not snapshot (asked as before)


def top_of(cwd: str) -> str:
    """The top folder of the repository a folder is in.

    Args:
        cwd: a folder.

    Returns:
        Its top folder with forward slashes; "" outside a repository, or when git cannot read it.
    """
    if not cwd or not os.path.isdir(cwd):
        return ""
    try:
        return str(git(cwd, "rev-parse", "--show-toplevel")).strip().replace("\\", "/")
    except GitError:
        return ""


def snapshot(root: str) -> Optional[Snapshot]:
    """The changed and untracked files of a repository, each with the hash of its content now.

    Args:
        root: the top folder of the repository.

    Returns:
        {path from root: content hash}; None when git cannot read root or more than MOST files changed.
    """
    try:
        out = str(git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames"))
    except GitError:
        return None
    paths = [entry[3:] for entry in out.split("\0") if len(entry) > 3]
    if len(paths) > MOST:
        return None
    return {path: content_hash(os.path.join(root, path)) for path in paths}


def changed(before: Snapshot, after: Snapshot) -> list[str]:
    """The files a command changed: dirty after it ran, with a content the snapshot before did not hold.

    Args:
        before: the snapshot before the command.
        after: the snapshot after it.

    Returns:
        Their paths from the top of the repository, sorted.
    """
    return sorted(path for path, digest in after.items() if before.get(path) != digest)
