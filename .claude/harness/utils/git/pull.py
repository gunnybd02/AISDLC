"""Bring the clone a harness home lives in up to its origin's main (live update, engine/cli_live.py): fast-forward
only, never over local changes, never off main. It changes the work tree only; what runs is the release in force, which
the user's word switches."""
from harness.utils.git.run import GitError, git, run_git

BRANCH = "main"


class PullError(ValueError):
    pass


def clone_root(home):
    """The top folder of the git clone the home is in; PullError when it is in none."""
    try:
        return git(home, "rev-parse", "--show-toplevel").strip()
    except GitError as e:
        raise PullError(f"the harness home is not in a git clone: {e}") from e


def fast_forward(home, timeout=120):
    """(the commit before, the commit after) of the home's clone, brought to origin's main; PullError with why when it
    cannot be done safely."""
    root = clone_root(home)
    try:
        branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        changed = git(root, "status", "--porcelain", "--untracked-files=no").strip()
        before = git(root, "rev-parse", "HEAD").strip()
    except GitError as e:
        raise PullError(str(e)) from e
    if branch != BRANCH:
        raise PullError(f"the harness clone is on {branch}, not {BRANCH}: update it by hand")
    if changed:
        raise PullError("the harness clone has local changes, which an update would mix in: "
                        + ", ".join(line[3:] for line in changed.splitlines()[:5]))
    for words in (["fetch", "-q", "origin", BRANCH], ["merge", "-q", "--ff-only", "FETCH_HEAD"]):
        code, out = run_git(root, words, timeout)
        if code != 0:
            raise PullError(f"git {' '.join(words)}: {out.strip() or f'exit {code}'}")
    return before, git(root, "rev-parse", "HEAD").strip()
