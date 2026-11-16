"""ChildGuard: what a child session of a delegated plan never does (docs/05b-orchestra-cloud.md part 2). Nobody is at
a child's keyboard, and only the orchestrator merges:
- child.ask_user: AskUserQuestion; nobody would answer it, and the child would wait for ever;
- child.merge: git merge, pull or rebase; the orchestrator merges the child's branch on accept;
- child.push_other: a git push to any branch but its own (orch/p<plan>/<name>).
The port's child_role (() -> the session's ChildRole or None) says whether the session is a child; it is read only for
a call that could be one of these."""
from __future__ import annotations

from harness.gear.detect.git import push_parts
from harness.utils.contracts import Detector, Event, Finding
from harness.utils.shapes import Facts

MERGES = ("merge", "pull", "rebase")


def pushed_branches(args: list[str], own: str) -> list[str]:
    """The branches a git push sends to that are not own: each refspec's destination; a push with no refspec sends the
    current branch, which the child's push action checks.

    Args:
        args: the words after git push.
        own: the child's branch.

    Returns:
        The other destinations; ["--all"] or ["--mirror"] for a push of every branch.
    """
    options, _, refspecs = push_parts(args)
    every = [o for o in options if o in ("--all", "--mirror", "--tags")]
    others = []
    for spec in refspecs:
        src, _, dst = spec.lstrip("+").partition(":")
        branch = (dst or src).removeprefix("refs/heads/")
        if branch not in (own, "HEAD"):
            others.append(branch)
    return every + others


class ChildGuard(Detector):
    """What a child never does: child.ask_user, child.merge, child.push_other."""

    def detect(self, event: Event, facts: Facts) -> list[Finding]:
        """Report the findings of a child's call before it runs; nothing for a session that is no child."""
        if event.kind != "PreToolUse" or "child_role" not in facts:
            return []
        actions = facts.get("git_actions") or []
        gits = [a for a in actions if a.get("sub") in MERGES + ("push",)]
        if event.tool != "AskUserQuestion" and not gits:
            return []
        role = facts["child_role"]()
        if not role:
            return []
        if event.tool == "AskUserQuestion":
            return [Finding("child.ask_user", f"the child {role['name']} asked the user")]
        out = []
        for action in gits:
            if action["sub"] in MERGES:
                out.append(Finding("child.merge", f"git {action['sub']} in the child {role['name']}"))
            else:
                others = pushed_branches(action.get("args", []), role["branch"])
                if others:
                    out.append(Finding("child.push_other", f"git push to {', '.join(others)}"))
        return out
