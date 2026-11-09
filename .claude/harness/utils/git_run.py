"""git: every git command of the harness. Arguments are a list, never a shell string; each run has a timeout; the
GIT_* variables a caller may leave behind (GIT_DIR, GIT_INDEX_FILE...) are taken out, so the repository given is the
one read."""
import os
import subprocess
from pathlib import Path

TIMEOUT = 30


class GitError(RuntimeError):
    pass


def env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(repo, *args, timeout=TIMEOUT, binary=False):
    """The output of `git -C repo args`; a failure raises GitError with git's own words."""
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=timeout, env=env())
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitError(f"git {' '.join(args)}: {e}") from e
    if p.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {p.stderr.decode('utf-8', 'replace').strip()}")
    return p.stdout if binary else p.stdout.decode("utf-8", "replace")


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


def staged(repo):
    """{path from the repository root: the blob id it stages, or None when the change deletes it}. Blob ids are what
    git stores after its own filters (line ends...), so they compare with blob() of the same content."""
    parts = git(repo, "diff", "--cached", "--raw", "--no-abbrev", "-z").split("\0")
    out, i = {}, 0
    while i + 1 < len(parts) and parts[i].startswith(":"):
        fields = parts[i].split()
        status, path = fields[4], parts[i + 1]
        if status[0] in "RC":  # a rename or copy names two paths: the old one, then the new one
            out[parts[i + 2]] = fields[3]
            i += 3
            continue
        out[path] = None if status[0] == "D" else fields[3]
        i += 2
    return out


def blob(root, path):
    """The blob id git would store for the file at path (from root), or None when there is no such file."""
    if not (Path(root) / path).is_file():
        return None
    return git(root, "hash-object", "--", path).strip()


