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
from harness.gear.detect.commit import CommitGate
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


PLAN = {"id": 7, "plan_id": "pd-1", "rev": 1, "root": "C:/r", "title": "t", "files": ["a.py"], "tests": ["test_a.py"]}


def kinds(commit, plan=PLAN, unsafe=""):
    facts = {"plan": plan, "git_commit": {"repo": "C:/r", "unsafe": unsafe}, "commit_view": lambda repo, plan_row: commit}
    return [f.kind for f in CommitGate().detect(bash("git commit", "C:/r"), facts)]


class CommitGateTest(unittest.TestCase):
    def commit(self, receipt, staged_files, repo="C:/r"):
        return {"repo": repo, "plan_repo": "C:/r", "staged": staged_files, "receipt": receipt}

    def test_an_unsafe_commit_is_refused_before_anything_else(self):
        self.assertEqual(kinds(self.commit({"ok": 1, "files": {}}, {}), unsafe="compound"), ["commit.unsafe"])
        self.assertEqual(kinds(None, plan=None, unsafe="compound"), ["commit.unsafe"])

    def test_a_commit_in_another_repository_than_the_plans_is_refused(self):
        self.assertEqual(kinds(self.commit({"ok": 1, "files": {"a.py": "h1"}}, {"a.py": "h1"}, repo="C:/other")),
                         ["commit.outside"])

    def test_a_commit_without_a_passing_verify_is_refused(self):
        self.assertEqual(kinds(self.commit(None, {"a.py": "h1"})), ["commit.unverified"])
        self.assertEqual(kinds(self.commit({"ok": 0, "files": {"a.py": "h1"}}, {"a.py": "h1"})), ["commit.unverified"])

    def test_a_file_changed_after_the_verify_is_refused(self):
        self.assertEqual(kinds(self.commit({"ok": 1, "files": {"a.py": "h1"}}, {"a.py": "h2"})), ["commit.changed"])

    def test_a_staged_file_outside_the_plan_is_refused(self):
        found = kinds(self.commit({"ok": 1, "files": {"a.py": "h1"}}, {"a.py": "h1", "b.py": "h9"}))
        self.assertEqual(found, ["commit.outside"])

    def test_a_commit_without_a_plan_is_refused(self):
        self.assertEqual(kinds(self.commit(None, {"a.py": "h1"}), plan=None), ["plan.none"])

    def test_a_verified_commit_of_plan_files_passes(self):
        self.assertEqual(kinds(self.commit({"ok": 1, "files": {"a.py": "h1"}}, {"a.py": "h1"})), [])

    def test_the_rules_refuse_each_finding_and_the_recipe_runs_the_gate(self):
        rules = Decide.load(CLAUDE_DIR).rules
        for kind in ("commit.unverified", "commit.changed", "commit.outside", "commit.unsafe"):
            self.assertEqual(rules[kind]["verdict"], "refuse")
        names = {i["name"] for i in gear_block.ITEMS}
        self.assertLessEqual({"git_commands", "commit_gate"}, names)


if __name__ == "__main__":
    unittest.main()
