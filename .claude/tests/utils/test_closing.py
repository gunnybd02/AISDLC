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


class CommitFlowTest(unittest.TestCase):
    """Through the runner with a real repository: refused before verify, allowed after, delivered once committed."""

    def setUp(self):
        self.claude_dir = copy_tree(self, {"project.json": json.dumps(
            {"name": "t", "verify": ["{python}", "-m", "unittest", "discover", "-s", "."]})})
        self.repo = git_repo(self, {"a.py": "X = 1\n", "test_a.py": "import unittest\n\nclass T(unittest.TestCase):\n"
                                                                   "    def test_x(self):\n        pass\n"})
        self.port, self.runner = LedgerPort(self.claude_dir), build_runner(self.claude_dir)
        self.plan_id, _, q = self.port.present({"title": "t", "files": ["a.py"], "tests": ["test_a.py"],
                                                "root": str(self.repo)})
        self.runner.run(Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": q}],
                                                                 "answers": {q: "Duyệt"}}, "s1", str(self.repo)))

    def test_a_commit_that_did_not_come_from_the_approval_point_delivers_nothing(self):
        verify(self.port, Config.load(self.claude_dir).verify, self.plan_id)
        git(self.repo, "commit", "--allow-empty", "-q", "-m", "unseen one")
        git(self.repo, "commit", "--allow-empty", "-q", "-m", "unseen two")
        notes = self.runner.run(bash("git commit -m x", self.repo, "PostToolUse")).notes
        self.assertIn("not made right on the commit of the approval", " ".join(notes))
        self.assertIsNotNone(self.port.approved("s1"))

    def test_a_commit_that_holds_more_than_the_verified_plan_delivers_nothing(self):
        verify(self.port, Config.load(self.claude_dir).verify, self.plan_id)
        (self.repo / "z.py").write_text("unvetted\n", encoding="utf-8")
        git(self.repo, "add", "z.py")
        git(self.repo, "commit", "-q", "-m", "made around the gate")  # parent is the base, as the gate's would be
        notes = self.runner.run(bash("git commit -m x", self.repo, "PostToolUse")).notes
        self.assertIn("not delivered", " ".join(notes))
        self.assertIsNotNone(self.port.approved("s1"))

    def test_a_commit_of_other_content_than_the_verify_saw_delivers_nothing(self):
        (self.repo / "a.py").write_text("X = 2\n", encoding="utf-8")
        verify(self.port, Config.load(self.claude_dir).verify, self.plan_id)
        (self.repo / "a.py").write_text("X = 3\n", encoding="utf-8")
        git(self.repo, "add", "a.py")
        git(self.repo, "commit", "-q", "-m", "changed after the verify")
        self.runner.run(bash("git commit -m x", self.repo, "PostToolUse"))
        self.assertIsNotNone(self.port.approved("s1"))

    def test_a_commit_that_only_changes_a_mode_delivers_nothing(self):
        verify(self.port, Config.load(self.claude_dir).verify, self.plan_id)
        git(self.repo, "update-index", "--chmod=+x", "a.py")
        git(self.repo, "commit", "-q", "-m", "mode only")
        notes = self.runner.run(bash("git commit -m x", self.repo, "PostToolUse")).notes
        self.assertIn("not delivered", " ".join(notes))
        self.assertIsNotNone(self.port.approved("s1"))

    def test_an_empty_commit_delivers_nothing(self):
        verify(self.port, Config.load(self.claude_dir).verify, self.plan_id)
        git(self.repo, "commit", "--allow-empty", "-q", "-m", "nothing")
        notes = self.runner.run(bash("git commit -m x", self.repo, "PostToolUse")).notes
        self.assertIn("changes nothing", " ".join(notes))
        self.assertIsNotNone(self.port.approved("s1"))

    def test_a_repository_without_a_commit_at_the_approval_delivers_nothing_and_breaks_nothing(self):
        empty = tree(self, {"a.py": "X = 1\n"})
        git(empty, "init", "-q", "-b", "work")
        git(empty, "config", "user.name", "t")
        git(empty, "config", "user.email", "t@t")
        plan_id, _, q = self.port.present({"title": "first", "files": ["a.py"], "tests": [], "root": str(empty)})
        self.runner.run(Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": q}],
                                                                 "answers": {q: "Duyệt"}}, "s2", str(empty)))
        git(empty, "add", "a.py")
        git(empty, "commit", "-q", "-m", "root")
        event = Event("PostToolUse", "Bash", {"command": "git commit -m root"}, "s2", str(empty))
        notes = self.runner.run(event).notes
        self.assertIn("no commit", " ".join(notes))
        self.assertIsNotNone(self.port.approved("s2"))

    def test_a_path_that_differs_only_in_case_is_not_the_plan_file(self):
        verify(self.port, Config.load(self.claude_dir).verify, self.plan_id)
        git(self.repo, "mv", "a.py", "A.py")
        git(self.repo, "commit", "-q", "-m", "case")
        self.runner.run(bash("git commit -m x", self.repo, "PostToolUse"))
        self.assertIsNotNone(self.port.approved("s1"))

    def test_a_commit_in_a_folder_that_does_not_exist_is_refused(self):
        verify(self.port, Config.load(self.claude_dir).verify, self.plan_id)
        self.assertEqual(self.runner.run(bash("git -C nothere commit -m x", self.repo)).verdict.decision, "refuse")

    def test_a_commit_in_another_repository_delivers_nothing(self):
        other = git_repo(self, {"z.py": ""})
        verify(self.port, Config.load(self.claude_dir).verify, self.plan_id)
        git(other, "commit", "--allow-empty", "-q", "-m", "elsewhere")
        notes = self.runner.run(bash(f"git -C {other} commit --allow-empty -m elsewhere", self.repo, "PostToolUse")).notes
        self.assertEqual(notes, ())
        self.assertIsNotNone(self.port.approved("s1"))

    def test_verify_then_commit_delivers_the_plan(self):
        claude_dir, repo, port, runner, plan_id = self.claude_dir, self.repo, self.port, self.runner, self.plan_id
        (repo / "a.py").write_text("X = 2\n", encoding="utf-8")
        git(repo, "add", "a.py")
        commit = bash("git commit -m change", repo)
        self.assertEqual(runner.run(commit).verdict.decision, "refuse")
        self.assertIn("passed", verify(port, Config.load(claude_dir).verify, plan_id))
        self.assertEqual(runner.run(commit).verdict.decision, "allow")
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "change"], check=True)
        notes = runner.run(bash("git commit -m change", repo, "PostToolUse")).notes
        self.assertIn("delivered", " ".join(notes))
        self.assertIsNone(port.approved("s1"))
        row = port.ledger.one("SELECT commit_sha FROM rec_commits")
        self.assertEqual(row["commit_sha"], git(repo, "rev-parse", "HEAD").strip())


if __name__ == "__main__":
    unittest.main()
