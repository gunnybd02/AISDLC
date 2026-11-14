"""WriteAction: action.<block>.<name>, a write action of the MCP server about to run. Its rule row in
gear/rules/actions.json decides it; a write with no row is asked, which run refuses (the server cannot ask)."""
from harness.utils.contracts import Detector, Finding


class WriteAction(Detector):
    def detect(self, event, facts):
        target = facts.get("action_write")
        return [Finding(f"action.{target}", target)] if target else []
