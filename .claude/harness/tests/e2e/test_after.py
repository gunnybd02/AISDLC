"""s5.after.flow: entry/hook.py run as Claude Code runs it, in auto mode: a command the reader cannot see whole runs
with no ask, and after it ran the hook names each file it changed that no plan allows, beside its result. In another
mode the same command is still asked."""
import json
import unittest

from harness.tests import entry_of
from harness.tests.e2e import copy_tree, git_repo, run

SAID = "Build the project with its own script"


def hook(root, payload):
    return run(entry_of(root, "hook"), json.dumps(payload))


class AfterFlowTest(unittest.TestCase):
    def setUp(self):
        self.root = copy_tree(self)
        self.repo = git_repo(self, {"a.py": "A = 1\n"})
        self.pre = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "s", "cwd": str(self.repo),
                    "tool_input": {"command": "./build.sh --fast", "description": SAID}, "permission_mode": "auto",
                    "tool_use_id": "toolu_1"}

    def test_auto_mode_runs_an_unclear_command_and_names_what_it_changed(self):
        self.assertEqual(hook(self.root, self.pre)[:2], (0, ""))  # no ask
        (self.repo / "out.txt").write_text("built\n", encoding="utf-8")
        code, out, _ = hook(self.root, {**self.pre, "hook_event_name": "PostToolUse",
                                        "tool_response": {"stdout": "", "stderr": "", "interrupted": False}})
        answer = json.loads(out)
        self.assertEqual((code, answer["decision"]), (0, "block"))
        self.assertIn("out.txt", answer["reason"])
        self.assertIn("no plan is approved", answer["reason"])

    def test_a_command_that_changed_nothing_says_nothing_after(self):
        self.assertEqual(hook(self.root, self.pre)[:2], (0, ""))
        post = {**self.pre, "hook_event_name": "PostToolUse", "tool_response": {"stdout": "ok"}}
        self.assertEqual(hook(self.root, post)[:2], (0, ""))

    def test_in_another_mode_the_same_command_is_asked(self):
        code, out, _ = hook(self.root, {**self.pre, "permission_mode": "default", "tool_use_id": "toolu_2"})
        self.assertEqual((code, json.loads(out)["hookSpecificOutput"]["permissionDecision"]), (0, "ask"))


if __name__ == "__main__":
    unittest.main()
