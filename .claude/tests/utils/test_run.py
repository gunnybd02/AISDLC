"""h9.commit-gate: a commit goes through only when the plan's verify passed and no staged file changed since, and only
with files the plan names; a commit that went through is kept and delivers the plan."""
import json
import subprocess
import unittest

import harness.gear as gear_block
from harness.assemble.engine.config import Config
from harness.utils.plan.verify import verify
from harness.assemble.engine.build import build_runner
from harness.assemble.engine.ports import LedgerPort
from harness.gear.decide.arbiter import Decide
from harness.gear.translate.git import GitCommands
from harness.utils.contracts import Event
from harness.utils.git.facts import staged, top
from harness.utils.git.run import GitError, git
from tests import CLAUDE_DIR, tree
from tests.e2e import copy_tree, git_repo


def bash(command, cwd, kind="PreToolUse"):
    return Event(kind, "Bash", {"command": command}, "s1", str(cwd))


def commit_fact(command):
    return GitCommands().translate(bash(command, "C:/r")).get("git_commit")


class GitRunTest(unittest.TestCase):
    def test_git_runs_from_a_list_and_reads_the_staged_files(self):
        repo = git_repo(self, {"a.py": "x\n"})
        (repo / "a.py").write_text("y\n", encoding="utf-8")
        git(repo, "add", "a.py")
        self.assertEqual(top(repo / "a.py").lower(), str(repo).replace("\\", "/").lower())
        self.assertEqual(list(staged(repo)), ["a.py"])
        with self.assertRaises(GitError):
            git(repo, "no-such-command")

    def test_a_rename_shows_the_file_it_takes_away(self):
        repo = git_repo(self, {"secret.txt": "s\n"})
        git(repo, "mv", "secret.txt", "b.py")
        self.assertEqual(sorted(staged(repo)), ["b.py", "secret.txt"])
        self.assertIsNone(staged(repo)["secret.txt"])


if __name__ == "__main__":
    unittest.main()
