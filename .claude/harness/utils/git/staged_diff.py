"""What a commit would add: the added lines of each file to commit, against HEAD (a new file: all its lines). The
secret scan reads these, never the whole history. added_between gives the same for a branch over its base (harness
ci, utils/orchestra/ci.py); both read git's diff with one parser (parse_added)."""
from __future__ import annotations

import os
from collections.abc import Sequence

from harness.utils.git.run import GitError, git

LONGEST = 2_000_000  # characters read of one new file


def added_lines(repo: str, paths: Sequence[str]) -> dict[str, list[str]]:
    """{path from the repository root: [added lines]} of paths, against HEAD; a binary file adds no line.

    Args:
        repo: the repository's root.
        paths: the files to commit, from the repository root.

    Returns:
        {path: the lines the commit would add}; an untracked file gives its first LONGEST characters' lines, an
        unreadable one [].
    """
    try:
        diff = git(repo, "diff", "HEAD", "--no-color", "--no-renames", "--unified=0", "--", *paths) if paths else ""
    except GitError:
        diff = ""
    out = {p: [] for p in paths}
    for path, lines in parse_added(diff).items():
        out.setdefault(path, []).extend(lines)
    for p in paths:
        if not out.get(p) and os.path.isfile(os.path.join(repo, p)):
            try:
                tracked = git(repo, "ls-files", "--", p).strip()
            except GitError:
                tracked = ""
            if not tracked:
                try:
                    with open(os.path.join(repo, p), encoding="utf-8") as f:
                        out[p] = f.read(LONGEST).splitlines()
                except (OSError, UnicodeDecodeError):
                    out[p] = []
    return out


def parse_added(diff: str) -> dict[str, list[str]]:
    """The added lines of each file of a unified diff (a deleted file adds none).

    Args:
        diff: git diff's output, --unified=0 --no-renames.

    Returns:
        {path from the repository root: [added lines]}, for the files that add a line.
    """
    out: dict[str, list[str]] = {}
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif current is not None and line.startswith("+") and not line.startswith("+++"):
            out.setdefault(current, []).append(line[1:])
    return out


def added_between(repo: str, base: str, head: str) -> dict[str, list[str]]:
    """The added lines of each file a branch changes over its base (from their merge base).

    Args:
        repo: the repository's root.
        base: the base's ref.
        head: the branch's ref.

    Returns:
        {path: [added lines]}.

    Raises:
        GitError: git cannot read the refs.
    """
    return parse_added(git(repo, "diff", "--no-color", "--no-renames", "--unified=0", f"{base}...{head}"))
