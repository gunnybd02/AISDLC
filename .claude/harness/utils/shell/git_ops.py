"""The files a git command changes: a git that only reads writes nothing; one that changes the work tree, writes a file
or runs a program is Unseen. A push writes no local file (the git rules judge where it goes: gear/translate/git_rules.py),
and a new branch made at HEAD (checkout -b, switch -c, no start point, no path) changes no file."""
from __future__ import annotations

from collections.abc import Sequence

from harness.utils.shell.command import Word
from harness.utils.shell.paths import Target, Unseen

GIT_NO_FILES = frozenset((
    "status diff log show rev-parse ls-files ls-tree blame grep describe shortlog cat-file rev-list for-each-ref "
    "name-rev diff-tree diff-index diff-files count-objects check-ignore var whatchanged help version add commit "
    "branch tag remote fetch ls-remote reflog show-ref merge-base push").split())
GIT_GLOBAL = {"--no-pager", "--paginate", "-p", "--no-optional-locks"}
GIT_RUNS = ("--upload-pack", "--receive-pack", "--exec")
NEW_BRANCH = {"checkout": {"-b", "-B"}, "switch": {"-c", "-C", "--create", "--force-create"}}
QUIET = {"-q", "--quiet"}


def new_branch(sub: str, rest: Sequence[Word]) -> bool:
    """Whether a checkout or switch only makes a branch at HEAD and moves to it: its create option and the new name,
    -q at most, no start point, no path. The work tree keeps every file as it is.

    Args:
        sub: the git subcommand.
        rest: the words after it.

    Returns:
        True for checkout -b <name> or switch -c <name> (-B, -C, --create, --force-create too) and nothing else.
    """
    words = [w for w in rest if w.text not in QUIET]
    return sub in NEW_BRANCH and len(words) == 2 and words[0].text in NEW_BRANCH[sub] and \
        not words[1].dynamic and not words[1].text.startswith("-")


def git(ws: Sequence[Word]) -> list[Target]:
    """The places a git command writes: none for a git that only reads.

    Args:
        ws: the words after git.

    Returns:
        [] (a git the reader lets through writes no file it names).

    Raises:
        Unseen: a global option it does not follow, a subcommand that changes the work tree or reaches another
            place, or an option that writes a file or runs a program.
    """
    i = 0
    while i < len(ws) and ws[i].text.startswith("-"):
        if ws[i].text == "-C":
            i += 2
            continue
        if ws[i].text not in GIT_GLOBAL:
            raise Unseen(f"git {ws[i].text} is a global option the reader does not follow")
        i += 1
    sub, rest = (ws[i].text if i < len(ws) else ""), ws[i + 1:]
    if sub == "config" and rest and all(w.text in ("-l", "--list", "--show-origin") or w.text.startswith("--get")
                                        or not w.text.startswith("-") for w in rest) and \
            any(w.text in ("-l", "--list") or w.text.startswith("--get") for w in rest):
        return []
    if new_branch(sub, rest):
        return []
    if sub not in GIT_NO_FILES:
        raise Unseen(f"git {sub or '(nothing)'} changes the work tree or reaches another place")
    if any(w.text.startswith(("--output", "--open-files-in-pager", "--ext-diff") + GIT_RUNS) or w.text == "-O"
           or (w.text == "-u" and sub in ("fetch", "ls-remote")) for w in rest):
        raise Unseen(f"git {sub} writes a file or runs a program")
    return []
