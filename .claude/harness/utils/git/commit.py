"""The commit the harness makes for a plan: only the paths given, whatever else the index holds. `git add` stages them
(a deletion too), `git commit --only` records exactly them; the repository's own hooks run as for any commit."""
from harness.utils.git.run import git


def changed(repo, paths):
    """The paths (from the repository root) whose working tree differs from HEAD: changed, new or deleted."""
    out = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames", "--", *paths)
    return sorted({entry[3:] for entry in out.split("\0") if len(entry) > 3})


def commit(repo, paths, message):
    """Commit exactly paths with message; the new HEAD."""
    git(repo, "add", "--all", "--", *paths)
    git(repo, "commit", "--only", "-q", "-m", message, "--", *paths)
    return git(repo, "rev-parse", "HEAD").strip()
