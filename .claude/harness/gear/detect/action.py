"""WriteAction: action.<block>.<name>, a write action of the MCP server about to run. Its rule row in
gear/rules/actions.json decides it; a write with no row is asked, which run refuses (the server cannot ask)."""
from __future__ import annotations

from harness.utils.contracts import Detector, Event, Finding
from harness.utils.shapes import Facts


class WriteAction(Detector):
    """A write action of the MCP server about to run: action.<block>.<name>."""

    def detect(self, event: Event, facts: Facts) -> list[Finding]:
        """Report action.<block>.<name> for a write action of the MCP server about to run (the fact action_write)."""
        target = facts.get("action_write")
        return [Finding(f"action.{target}", target)] if target else []
