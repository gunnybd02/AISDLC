"""Facts read with git: the root of a repository, its HEAD, what the index or a commit changes, a file's blob id."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from harness.utils.git.run import GitError, git
from harness.utils.shapes import RawChange


def top(path: str | Path) -> Optional[str]:
    """The root of the repository holding path, with forward slashes; None outside a repository.

    Args:
        path: a folder or a file (its folder is asked).

    Returns:
        The root folder, or None.
    """
    folder = Path(path) if Path(path).is_dir() else Path(path).parent
    try:
        return git(folder, "rev-parse", "--show-toplevel").strip().replace("\\", "/")
    except GitError:
        return None


def head(repo: str | Path) -> Optional[str]:
    """The commit HEAD names.

    Args:
        repo: the repository.

    Returns:
        The full sha, or None (no repository, or no commit yet).
    """
    try:
        return git(repo, "rev-parse", "HEAD").strip()
    except GitError:
        return None


def raw_changes(repo: str | Path, *args: str) -> dict[str, RawChange]:
    """{path from the repository root: (old mode, new mode, new blob id)}, a mode None where the path is absent and the
    blob None when the change deletes it; from `git diff --raw` with renames off (a rename shows as the path it takes
    away and the path it adds) and every submodule change shown, whatever the repository's config says.

    Args:
        repo: the repository.
        *args: what git diff compares ("--cached", or two commits).

    Returns:
        {path: (old mode, new mode, new blob id)}.

    Raises:
        GitError: git diff fails.
    """
    parts = git(repo, "diff", "--raw", "--no-abbrev", "--no-renames", "--ignore-submodules=none", "-z",
                *args).split("\0")
    out, i = {}, 0
    while i + 1 < len(parts) and parts[i].startswith(":"):
        old, new, _, blob_id, status = parts[i].lstrip(":").split()[:5]
        absent = "000000"
        out[parts[i + 1]] = (None if old == absent else old, None if new == absent else new,
                             None if status.startswith("D") else blob_id)
        i += 2
    return out


def staged(repo: str | Path) -> dict[str, Optional[str]]:
    """{path: blob id or None} the index changes against HEAD. Blob ids are what git stores after its own filters
    (line ends...), so they compare with blob() of the same content.

    Args:
        repo: the repository.

    Returns:
        {path from the repository root: the staged blob id, None for a deletion}.

    Raises:
        GitError: git diff fails.
    """
    return {path: blob_id for path, (_, _, blob_id) in raw_changes(repo, "--cached").items()}


def committed(repo: str | Path, base: str, sha: str) -> dict[str, RawChange]:
    """{path: (old mode, new mode, blob id)} the commit sha changes against base.

    Args:
        repo: the repository.
        base: the commit compared from.
        sha: the commit compared to.

    Returns:
        {path: (old mode, new mode, new blob id)} as raw_changes gives it.

    Raises:
        GitError: git diff fails.
    """
    return raw_changes(repo, base, sha)


def parent(repo: str | Path, sha: str) -> Optional[str]:
    """The first parent of a commit, or None for a root commit.

    Args:
        repo: the repository.
        sha: the commit.

    Returns:
        The parent's full sha, or None (a root commit, or git fails).
    """
    try:
        return git(repo, "rev-parse", f"{sha}^").strip()
    except GitError:
        return None


def blob(root: str | Path, path: str) -> Optional[str]:
    """The blob id git would store for the file at path (from root), or None when there is no such file.

    Args:
        root: the repository's root (or the plan's root).
        path: the file, relative to root.

    Returns:
        The blob id, or None when no such file.

    Raises:
        GitError: git hash-object fails.
    """
    if not (Path(root) / path).is_file():
        return None
    return git(root, "hash-object", "--", path).strip()




def unpushed_files(repo: str | Path, remote: str, source: str = "HEAD") -> list[str]:
    """The paths the commits of source change that no ref of remote holds yet: what a push of source would send.

    Args:
        repo: the repository.
        remote: the remote's name (origin).
        source: the commit or branch pushed.

    Returns:
        The paths, sorted; [] when git fails.
    """
    try:
        out = git(repo, "log", "--name-only", "--format=", source, "--not", f"--remotes={remote}")
    except GitError:
        return []
    return sorted({line.strip() for line in out.splitlines() if line.strip()})
