"""h2.one-verdict-path: the hook JSON of Claude Code becomes an Event; a verdict becomes its permissionDecision."""
import json
import unittest

import harness.mcp as mcp_block
from harness.mcp.hooks import HookError, HookIO
from harness.utils.contracts import ALLOW, ASK, REFUSE, Event, Verdict

PAYLOAD = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"},
           "session_id": "s1", "cwd": "C:/x"}


class HookIOTest(unittest.TestCase):
    def test_a_payload_becomes_an_event(self):
        self.assertEqual(HookIO.read(json.dumps(PAYLOAD)), Event("PreToolUse", "Bash", {"command": "ls"}, "s1", "C:/x"))

    def test_a_payload_that_is_not_a_hook_event_is_refused(self):
        for text in ("not json", "[]", json.dumps({"tool_name": "Bash"}), json.dumps({**PAYLOAD, "tool_input": "x"})):
            with self.subTest(text=text), self.assertRaises(HookError):
                HookIO.read(text)

    def test_allow_says_nothing(self):
        self.assertEqual(HookIO.write(Event("PreToolUse"), Verdict(ALLOW)), "")

    def test_ask_and_refuse_become_the_decisions_claude_code_reads(self):
        for verdict, word in ((ASK, "ask"), (REFUSE, "deny")):
            with self.subTest(verdict=verdict):
                out = json.loads(HookIO.write(Event("PreToolUse"), Verdict(verdict, "why")))["hookSpecificOutput"]
                self.assertEqual((out["permissionDecision"], out["permissionDecisionReason"]), (word, "why"))

    def test_an_event_other_than_pre_tool_use_gets_no_decision(self):
        self.assertEqual(HookIO.write(Event("PostToolUse"), Verdict(REFUSE, "why")), "")

    def test_mcp_declares_hook_io_as_its_hook(self):
        self.assertIn({"kind": "hook", "name": "hook_io", "ref": "harness.mcp.hooks:HookIO"}, mcp_block.ITEMS)


if __name__ == "__main__":
    unittest.main()
