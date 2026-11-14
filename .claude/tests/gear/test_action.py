"""h3.write-judged: a write action of the MCP server is a finding its rule row decides; one with no row is asked."""
import unittest

from harness.gear.decide.arbiter import Decide
from harness.gear.detect.action import WriteAction
from harness.gear.translate.action import Actions
from harness.utils.contracts import Event
from tests import CLAUDE_DIR
from tests.mcp.test_action_registry import PINNED


def kinds(block, action, effect="write", tool="mcp__harness__run"):
    event = Event("PreToolUse", tool, {"block": block, "action": action, "args": {}, "effect": effect})
    return [f.kind for f in WriteAction().detect(event, Actions().translate(event))]


class WriteActionTest(unittest.TestCase):
    def test_a_write_call_of_the_run_tool_is_a_finding(self):
        self.assertEqual(kinds("plan", "plan_present"), ["action.plan.plan_present"])
        self.assertEqual(kinds("plan", "plan_present", effect="read"), [])
        self.assertEqual(kinds("plan", "plan_present", tool="Bash"), [])

    def test_each_write_action_of_the_server_has_its_rule(self):
        rules = Decide.load(CLAUDE_DIR).rules
        writes = [name for name, effect in PINNED.items() if effect == "write"]
        for name in writes:
            with self.subTest(action=name):
                self.assertEqual(rules[f"action.{name}"]["verdict"], "allow")

    def test_a_write_with_no_rule_is_asked(self):
        from harness.utils.contracts import Finding
        self.assertEqual(Decide.load(CLAUDE_DIR).decide([Finding("action.x.new")]).decision, "ask")


if __name__ == "__main__":
    unittest.main()
