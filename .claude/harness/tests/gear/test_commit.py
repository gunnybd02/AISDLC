"""h9.commit-gate: a commit from the shell is refused, safe to read or not; commits go through step_done, where the
harness checks the plan's change and commits it (tests/utils/test_steps.py)."""
import unittest

import harness.gear as gear_block
from harness.gear.decide.arbiter import Decide
from harness.gear.translate.git_rules import ShellCommit
from harness.gear.translate.git import GitCommands
from harness.utils.contracts import Event
from harness.tests import CLAUDE_DIR


def bash(command, kind="PreToolUse"):
    return Event(kind, "Bash", {"command": command}, "s1", "C:/r")


JUDGE = Decide.load(CLAUDE_DIR)


def found(command, kind="PreToolUse"):
    """The findings of the real when rows: GitCommands, then ShellCommit."""
    event = bash(command, kind)
    return JUDGE.matched(ShellCommit().translate(event, GitCommands().translate(event)).get("rule_actions", []))


def kinds(command, kind="PreToolUse"):
    return [f.kind for f in found(command, kind)]


class RawCommitTest(unittest.TestCase):
    def test_every_commit_from_the_shell_is_refused(self):
        for command in ("git commit -m x", "git -C sub commit -q -m x", "git add a && git commit -m x",
                        "env A=1 git commit -m x", "git merge feature"):
            with self.subTest(command=command):
                self.assertEqual(kinds(command), ["commit.raw"])
        self.assertEqual(JUDGE.codes["commit.raw"]["verdict"], "refuse")
        self.assertEqual(JUDGE.codes["commit.raw"]["when"], {"kind": "commit"})
        self.assertIn("run('plan', 'step_done', {message})", JUDGE.codes["commit.raw"]["why"])  # found live
        self.assertEqual(found("git -C sub commit -q -m x")[0].detail, "git commit in C:/r/sub")  # the same words

    def test_a_line_that_does_not_commit_is_no_finding(self):
        for command in ("git status", "git add a.py", "git diff --cached", "ls"):
            with self.subTest(command=command):
                self.assertEqual(kinds(command), [])

    def test_only_a_call_before_it_runs_is_judged(self):
        self.assertEqual(kinds("git commit -m x", "PostToolUse"), [])

    def test_commit_raw_is_a_when_row_and_its_detector_is_gone(self):
        self.assertNotIn("raw_commit", {i["name"] for i in gear_block.ITEMS})
        self.assertIn("shell_commit", {i["name"] for i in gear_block.ITEMS})


if __name__ == "__main__":
    unittest.main()
