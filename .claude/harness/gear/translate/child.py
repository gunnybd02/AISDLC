"""ChildCalls: the calls of a child session of a delegated plan, as rule actions (kind child, what: ask_user, call,
merge or push_other); the when rows decide what a child never does (docs/05b-orchestra-cloud.md part 2). Nobody is at
a child's keyboard, and only the orchestrator merges:
- child.ask_user: AskUserQuestion; nobody would answer it, and the child would wait for ever;
- child.merge: git merge, pull or rebase; the orchestrator merges the child's branch on accept;
- child.push_other: a git push to any branch but its own (orch/p<plan>/<name>);
- child.no_keyboard: every call of a child, a stand-in for the person who is not there: it counts only when the call
  would ask (gear/decide/arbiter.py IN_PLACE_OF_ASK), and then the child is told to go on instead of waiting.
The port's child_role (() -> the session's ChildRole or None) says whether the session is a child; it is read for every
call before it runs (one read of the session's ticket)."""
from __future__ import annotations

from typing import Any, Optional

from harness.gear.translate.git_rules import push_parts
from harness.utils.contracts import RULE_ACTIONS, Event, Translator
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


def what_of(event: Event) -> str:
    """A short name of a call for the record: the tool and the first word of its command or its file, never the whole
    command (it may hold a secret).

    Args:
        event: the hook call.

    Returns:
        "<tool> <first word or file>".
    """
    command, path = event.input.get("command"), event.input.get("file_path") or event.input.get("path")
    word = command.split()[0][:60] if isinstance(command, str) and command.split() else str(path or "")[:120]
    return f"{event.tool} {word}".strip()


class ChildCalls(Translator):
    """The rule actions of a child's call before it runs: ask_user, or call (child.no_keyboard) with each merge and
    push_other."""
    READS = ("child_role", "git_actions")
    VOCABULARY = ("kind", "what")

    def translate(self, event: Event, facts: Optional[Facts] = None) -> Facts:
        """The child's rule actions before a call runs; {} for a session that is no child."""
        facts = facts or {}
        if event.kind != "PreToolUse" or "child_role" not in facts:
            return {}
        role = facts["child_role"]()
        if not role:
            return {}

        def act(what: str, detail: str) -> dict[str, Any]:
            return {"kind": "child", "what": what, "detail": detail}
        if event.tool == "AskUserQuestion":
            return {RULE_ACTIONS: [act("ask_user", f"the child {role['name']} asked the user")]}
        out = [act("call", what_of(event))]
        for action in [a for a in facts.get("git_actions") or [] if a.get("sub") in MERGES + ("push",)]:
            if action["sub"] in MERGES:
                out.append(act("merge", f"git {action['sub']} in the child {role['name']}"))
            else:
                others = pushed_branches(action.get("args", []), role["branch"])
                if others:
                    out.append(act("push_other", f"git push to {', '.join(others)}"))
        return {RULE_ACTIONS: out}
