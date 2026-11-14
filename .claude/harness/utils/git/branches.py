"""Branches: which ones are protected (names or patterns, fnmatch: main, release/*), and the branch a repository is on."""
from fnmatch import fnmatchcase

from harness.utils.git.run import GitError, git

DEFAULT_PROTECTED = ("main", "master")


def is_protected(branch, patterns):
    name = str(branch or "").removeprefix("refs/heads/")
    return bool(name) and any(fnmatchcase(name, p) for p in patterns)


def current(repo):
    """The branch the repository is on, or "" (detached, or no repository)."""
    try:
        return git(repo, "symbolic-ref", "--short", "-q", "HEAD").strip()
    except GitError:
        return ""
