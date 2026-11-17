"""h3.write-judged: a write action of the MCP server is a rule action its when row decides; one with no row is asked."""
import unittest

from harness.gear.decide.arbiter import Decide
from harness.gear.translate.action import Actions
from harness.utils.contracts import Event
from harness.tests import CLAUDE_DIR
from harness.tests.mcp.test_action_registry import PINNED


JUDGE = Decide.load(CLAUDE_DIR)


def kinds(block, action, effect="write", tool="mcp__harness__run"):
    event = Event("PreToolUse", tool, {"block": block, "action": action, "args": {}, "effect": effect})
    return [f.kind for f in JUDGE.matched(Actions().translate(event).get("rule_actions", []))]


class WriteActionTest(unittest.TestCase):
    def test_a_write_call_of_the_run_tool_is_a_finding(self):
        self.assertEqual(kinds("plan", "plan_present"), ["action.plan.plan_present"])
        self.assertEqual(kinds("plan", "plan_present", effect="read"), [])
        self.assertEqual(kinds("plan", "plan_present", tool="Bash"), [])

    def test_each_write_action_of_the_server_has_its_rule(self):
        writes = [name for name, effect in PINNED.items() if effect == "write"]
        for name in writes:
            with self.subTest(action=name):
                self.assertEqual(JUDGE.codes[f"action.{name}"]["verdict"], "allow")
                self.assertEqual(JUDGE.codes[f"action.{name}"]["when"], {"kind": "mcp_action", "name": name})
                block, _, action = name.partition(".")
                self.assertEqual(kinds(block, action), [f"action.{name}"])  # the same finding as before

    def test_a_write_with_no_rule_is_asked(self):
        found = JUDGE.matched(Actions().translate(Event("PreToolUse", "mcp__harness__run",
                                                        {"block": "x", "action": "new", "effect": "write"})).get("rule_actions"))
        self.assertEqual([f.kind for f in found], ["rule.unmatched"])
        self.assertEqual(JUDGE.decide(found).decision, "ask")  # never allowed: run refuses an unjudged write


if __name__ == "__main__":
    unittest.main()
