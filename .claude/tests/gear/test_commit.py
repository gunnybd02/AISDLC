"""h9.commit-gate: a commit from the shell is refused, safe to read or not; commits go through step_done, where the
harness checks the plan's change and commits it (tests/utils/test_steps.py)."""
import unittest

import harness.gear as gear_block
from harness.gear.decide.arbiter import Decide
from harness.gear.detect.commit import RawCommit
from harness.gear.translate.git import GitCommands
from harness.utils.contracts import Event
from tests import CLAUDE_DIR


def bash(command, kind="PreToolUse"):
    return Event(kind, "Bash", {"command": command}, "s1", "C:/r")


def kinds(command, kind="PreToolUse"):
    event = bash(command, kind)
    return [f.kind for f in RawCommit().detect(event, GitCommands().translate(event))]


class RawCommitTest(unittest.TestCase):
    def test_every_commit_from_the_shell_is_refused(self):
        for command in ("git commit -m x", "git -C sub commit -q -m x", "git add a && git commit -m x",
                        "env A=1 git commit -m x", "git merge feature"):
            with self.subTest(command=command):
                self.assertEqual(kinds(command), ["commit.raw"])
        self.assertEqual(Decide.load(CLAUDE_DIR).rules["commit.raw"]["verdict"], "refuse")
        self.assertIn("step_done", Decide.load(CLAUDE_DIR).rules["commit.raw"]["why"])
        self.assertIn("run('plan', 'step_done', {message})", Decide.load(CLAUDE_DIR).rules["commit.raw"]["why"])  # found live

    def test_a_line_that_does_not_commit_is_no_finding(self):
        for command in ("git status", "git add a.py", "git diff --cached", "ls"):
            with self.subTest(command=command):
                self.assertEqual(kinds(command), [])

    def test_only_a_call_before_it_runs_is_judged(self):
        self.assertEqual(kinds("git commit -m x", "PostToolUse"), [])

    def test_gear_declares_the_detector_and_the_floor_runs_it(self):
        self.assertIn("raw_commit", {i["name"] for i in gear_block.ITEMS})


if __name__ == "__main__":
    unittest.main()
