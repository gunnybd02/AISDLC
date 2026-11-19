"""MergeCalls: a merge of a pull request, as a rule action (kind merge_pr, op no_pass or no_head); the when rows
merge.no_pass and merge.no_head refuse it (utils/forge/merges.py: the user allows each merge).

A merge tool is known by its name, whatever its server is called (mcp__github__merge_pull_request, mcp__<id>__...). It
runs only when the ledger holds the user's pass for exactly its pull request and head commit (expectedHeadSha); else
the refusal carries the form question in its detail. A merge with no full head sha is refused: the user allows one
commit, not whatever the branch holds later. The port's merge_pass (code -> bool) reads the pass."""
from __future__ import annotations

from typing import Any, Optional

from harness.utils.contracts import RULE_ACTIONS, Event, Translator
from harness.utils.forge import merges
from harness.utils.shapes import Facts


def act(op: str, detail: str) -> Facts:
    """One rule action of kind merge_pr.

    Args:
        op: no_pass or no_head.
        detail: what the refusal shows in brackets.

    Returns:
        The facts with the action.
    """
    return {RULE_ACTIONS: [{"kind": "merge_pr", "op": op, "detail": detail}]}


class MergeCalls(Translator):
    """The rule action of a merge the user has not allowed."""
    VOCABULARY = ("kind", "op")
    READS = ("merge_pass",)

    def translate(self, event: Event, facts: Optional[Facts] = None) -> Facts:
        """Before a merge tool call: no_head without a full expectedHeadSha, no_pass without the user's pass; {} for a
        merge the user allowed and for every other call."""
        tool = str(event.tool or "")
        if event.kind != "PreToolUse" or not tool.startswith("mcp__") or not tool.endswith(merges.TOOL):
            return {}
        named = merges.target(event.input)
        if not named or not named[3]:
            which = f"PR #{named[2]} of {named[0]}/{named[1]}" if named else "the pull request"
            return act("no_head", which)
        held: Any = (facts or {}).get("merge_pass")
        if callable(held) and held(merges.code_of(*named)):
            return {}
        return act("no_pass", merges.question(*named))
