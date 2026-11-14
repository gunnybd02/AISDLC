"""h2.one-verdict-path (AC3): entry/hook.py run as Claude Code runs it: a plain call says nothing, a finding no rule
names asks the user, a broken harness exits 2."""
import json
import unittest

import harness.gear as gear_block
import harness.hooks as hooks_block
from tests.e2e import copy_tree, run

PAYLOAD = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": "s",
           "cwd": "C:/x"}
FAKE = {
    "harness/gear/fake_detect.py": (
        '"""A detector for the test."""\nfrom harness.utils.contracts import Detector, Finding\n\n\n'
        'class Fake(Detector):\n    def detect(self, event, facts):\n'
        '        return [Finding("test.flagged", event.input.get("command", ""))] if event.input.get("flag") else []\n'),
    "harness/gear/__init__.py": (
        '"""x"""\nITEMS = [{"kind": "rule", "name": "decide", "ref": "harness.gear.decide.arbiter:Decide"},\n'
        '         {"kind": "detector", "name": "fake", "ref": "harness.gear.fake_detect:Fake"}]\n'),
    "harness/assemble/pipelines/base.json": json.dumps({"translators": [], "detectors": ["fake"]}),
}


def hook(root, payload):
    return run(root / "entry" / "hook.py", json.dumps(payload))


class HookEntryTest(unittest.TestCase):
    def test_the_hook_path_is_declared_by_the_blocks(self):
        names = {i["name"] for i in gear_block.ITEMS + hooks_block.ITEMS}
        self.assertLessEqual({"decide", "hook_io"}, names)

    def test_a_plain_call_says_nothing(self):
        self.assertEqual(hook(copy_tree(self), {**PAYLOAD, "tool_name": "Read", "tool_input": {}})[:2], (0, ""))

    def test_a_finding_without_a_rule_asks_the_user_with_its_name(self):
        code, out, _ = hook(copy_tree(self, FAKE), {**PAYLOAD, "tool_input": {"command": "rm x", "flag": True}})
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual((code, decision["permissionDecision"]), (0, "ask"))
        self.assertIn("test.flagged", decision["permissionDecisionReason"])
        self.assertIn("rm x", decision["permissionDecisionReason"])

    def test_a_command_the_reader_cannot_see_whole_asks_the_user_with_the_agents_words(self):
        said = "Build the project with its own script, which writes into build/"
        payload = {**PAYLOAD, "tool_input": {"command": "./build.sh --fast", "description": said}}
        code, out, _ = hook(copy_tree(self), payload)
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual((code, decision["permissionDecision"]), (0, "ask"))
        for part in (said, "./build.sh --fast", "build.sh"):
            self.assertIn(part, decision["permissionDecisionReason"])
        payload["tool_input"]["description"] = "./build.sh --fast"
        decision = json.loads(hook(copy_tree(self), payload)[1])["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("description", decision["permissionDecisionReason"])

    def test_a_known_read_through_the_shell_says_nothing(self):
        payload = {**PAYLOAD, "tool_input": {"command": "git status && ls -la | grep x", "description": "x"}}
        self.assertEqual(hook(copy_tree(self), payload)[:2], (0, ""))

    def test_a_broken_harness_exits_2(self):
        root = copy_tree(self, {"harness/assemble/engine/build.py": "raise RuntimeError('broken')\n"})
        code, out, err = hook(root, PAYLOAD)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("broken", err)

    def test_a_harness_that_exits_quietly_still_blocks(self):
        root = copy_tree(self, {"harness/assemble/engine/build.py": "raise SystemExit(0)\n"})
        self.assertEqual(hook(root, PAYLOAD)[0], 2)

    def test_a_payload_that_is_not_json_exits_2(self):
        self.assertEqual(run(copy_tree(self) / "entry" / "hook.py", "not json")[0], 2)


if __name__ == "__main__":
    unittest.main()
