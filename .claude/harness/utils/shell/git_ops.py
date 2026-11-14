"""The files a git command changes: a git that only reads writes nothing; one that changes the work tree, writes a file
or runs a program is Unseen."""
from harness.utils.shell.paths import Unseen

GIT_NO_FILES = frozenset((
    "status diff log show rev-parse ls-files ls-tree blame grep describe shortlog cat-file rev-list for-each-ref "
    "name-rev diff-tree diff-index diff-files count-objects check-ignore var whatchanged help version add commit "
    "branch tag remote fetch reflog show-ref merge-base").split())
GIT_GLOBAL = {"--no-pager", "--paginate", "-p", "--no-optional-locks"}
GIT_RUNS = ("--upload-pack", "--receive-pack", "--exec")


def git(ws):
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
    if sub not in GIT_NO_FILES:
        raise Unseen(f"git {sub or '(nothing)'} changes the work tree or reaches another place")
    if any(w.text.startswith(("--output", "--open-files-in-pager", "--ext-diff") + GIT_RUNS) or w.text == "-O"
           or (w.text == "-u" and sub == "fetch") for w in rest):
        raise Unseen(f"git {sub} writes a file or runs a program")
    return []
