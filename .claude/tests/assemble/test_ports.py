"""h15.ticket: the MCP server knows its session from the hook: the session whose prompt or harness tool call came last."""
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.utils.contracts import Event, Verdict
from tests import tree


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(tree(self, {}))

    def see(self, kind, tool, sid):
        Act(self.port).run(Event(kind, tool, {}, sid, "/r"), {}, Verdict("allow"))

    def test_the_last_session_to_call_the_harness_is_the_one(self):
        self.assertEqual(self.port.session(), "")
        self.see("UserPromptSubmit", "", "s1")
        self.assertEqual(self.port.session(), "s1")
        self.see("PreToolUse", "mcp__harness__run", "s2")
        self.assertEqual(self.port.session(), "s2")
        self.see("PreToolUse", "Bash", "s3")  # another tool says nothing about who calls the server
        self.see("PostToolUse", "mcp__harness__run", "s3")
        self.assertEqual(self.port.session(), "s2")
        self.see("PreToolUse", "mcp__harness__find", "s1")
        self.assertEqual(self.port.session(), "s1")


if __name__ == "__main__":
    unittest.main()
