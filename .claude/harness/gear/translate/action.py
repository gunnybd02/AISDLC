"""Actions: the rule action of a call of the harness's run tool that says it writes (mcp/tools/run.py builds that event
for a write action before it runs; Claude Code names the tool mcp__harness__run): kind mcp_action, name "block.name",
must_match. Its when row in gear/rules/actions.json decides it; a write no row names is rule.unmatched, asked, which run
refuses (the server cannot ask)."""
from __future__ import annotations

from harness.utils.contracts import RULE_ACTIONS, WRITE, Event, Translator
from harness.utils.shapes import Facts

RUN_TOOLS = ("mcp__harness__run",)


class Actions(Translator):
    """The rule action of a write action of the harness's run tool about to run."""
    VOCABULARY = ("kind", "name")

    def translate(self, event: Event) -> Facts:
        """One rule action (kind mcp_action, name "block.name", must_match) for a call of the run tool whose effect is
        write; else {}."""
        data = event.input
        if event.tool not in RUN_TOOLS or data.get("effect") != WRITE:
            return {}
        block, name = data.get("block"), data.get("action")
        if not (isinstance(block, str) and isinstance(name, str)):
            return {}
        return {RULE_ACTIONS: [{"kind": "mcp_action", "name": f"{block}.{name}", "must_match": True,
                                "detail": f"{block}.{name}"}]}
