"""Bring the clone a harness home lives in up to its origin's main (live update, engine/cli_live.py): fast-forward
only, never over local changes or files git does not track under harness/, never off main. It changes the work tree
only; the clone is then exactly origin's main, which live update may put in force (the merge was the user's word)."""
from __future__ import annotations

from pathlib import Path

from harness.utils.git.run import GitError, git, run_git

BRANCH = "main"


class PullError(ValueError):
    """The home's clone cannot be brought up to origin's main safely; the message says why."""


def clone_root(home: str | Path) -> str:
    """The top folder of the git clone the home is in; PullError when it is in none.

    Args:
        home: the harness home (a folder inside the clone).

    Returns:
        The clone's top folder.

    Raises:
        PullError: the home is in no git clone.
    """
    try:
        return git(home, "rev-parse", "--show-toplevel").strip()
    except GitError as e:
        raise PullError(f"the harness home is not in a git clone: {e}") from e


def fast_forward(home: str | Path, timeout: float = 120) -> tuple[str, str]:
    """(the commit before, the commit after) of the home's clone, brought to origin's main; PullError with why when it
    cannot be done safely.

    Args:
        home: the harness home (a folder inside the clone).
        timeout: the seconds each of git fetch and git merge may take.

    Returns:
        (the sha of HEAD before, the sha of HEAD after); the same twice when there was nothing to bring.

    Raises:
        PullError: no clone, not on main, local changes, files git does not track under harness/, or the fetch or
            the fast-forward fails.
    """
    root = clone_root(home)
    try:
        branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        changed = git(root, "status", "--porcelain", "--untracked-files=no").strip()
        loose = git(root, "status", "--porcelain", "--untracked-files=all", "--",
                    str(Path(home).resolve() / "harness")).strip()
        before = git(root, "rev-parse", "HEAD").strip()
    except GitError as e:
        raise PullError(str(e)) from e
    if branch != BRANCH:
        raise PullError(f"the harness clone is on {branch}, not {BRANCH}: update it by hand")
    if changed:
        raise PullError("the harness clone has local changes, which an update would mix in: "
                        + ", ".join(line[3:] for line in changed.splitlines()[:5]))
    loose = "\n".join(line for line in loose.splitlines() if line.startswith("??"))
    if loose:
        raise PullError("the harness clone has files git does not track under harness/, which a release would take "
                        "in: " + ", ".join(line[3:] for line in loose.splitlines()[:5]))
    for words in (["fetch", "-q", "origin", BRANCH], ["merge", "-q", "--ff-only", "FETCH_HEAD"]):
        code, out = run_git(root, words, timeout)
        if code != 0:
            raise PullError(f"git {' '.join(words)}: {out.strip() or f'exit {code}'}")
    return before, git(root, "rev-parse", "HEAD").strip()
