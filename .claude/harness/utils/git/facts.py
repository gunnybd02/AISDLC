"""Facts read with git: the root of a repository, its HEAD, what the index or a commit changes, a file's blob id."""
from pathlib import Path

from harness.utils.git.run import GitError, git


def top(path):
    """The root of the repository holding path, with forward slashes; None outside a repository."""
    folder = Path(path) if Path(path).is_dir() else Path(path).parent
    try:
        return git(folder, "rev-parse", "--show-toplevel").strip().replace("\\", "/")
    except GitError:
        return None


def head(repo):
    try:
        return git(repo, "rev-parse", "HEAD").strip()
    except GitError:
        return None


def raw_changes(repo, *args):
    """{path from the repository root: (old mode, new mode, new blob id)}, a mode None where the path is absent and the
    blob None when the change deletes it; from `git diff --raw` with renames off (a rename shows as the path it takes
    away and the path it adds) and every submodule change shown, whatever the repository's config says."""
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


def staged(repo):
    """{path: blob id or None} the index changes against HEAD. Blob ids are what git stores after its own filters
    (line ends...), so they compare with blob() of the same content."""
    return {path: blob_id for path, (_, _, blob_id) in raw_changes(repo, "--cached").items()}


def committed(repo, base, sha):
    """{path: (old mode, new mode, blob id)} the commit sha changes against base."""
    return raw_changes(repo, base, sha)


def parent(repo, sha):
    """The first parent of a commit, or None for a root commit."""
    try:
        return git(repo, "rev-parse", f"{sha}^").strip()
    except GitError:
        return None


def blob(root, path):
    """The blob id git would store for the file at path (from root), or None when there is no such file."""
    if not (Path(root) / path).is_file():
        return None
    return git(root, "hash-object", "--", path).strip()




def unpushed_files(repo, remote, source="HEAD"):
    """The paths the commits of source change that no ref of remote holds yet: what a push of source would send."""
    try:
        out = git(repo, "log", "--name-only", "--format=", source, "--not", f"--remotes={remote}")
    except GitError:
        return []
    return sorted({line.strip() for line in out.splitlines() if line.strip()})
