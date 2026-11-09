"""h9.commit-gate: a commit goes through only when the plan's verify passed and no staged file changed since, and only
with files the plan names; a commit that went through is kept and delivers the plan."""
import json
import subprocess
import unittest

import harness.gear as gear_block
from harness.assemble.blocks import verify
from harness.assemble.build import build_runner
from harness.assemble.ports import LedgerPort
from harness.gear.decide import Decide
from harness.gear.detect_commit import CommitGate
from harness.gear.translate_git import GitCommands
from harness.utils.contracts import Event
from harness.utils.git_run import GitError, git, staged, top
from tests import CLAUDE_DIR
from tests.e2e import copy_tree, git_repo


def bash(command, cwd, kind="PreToolUse"):
    return Event(kind, "Bash", {"command": command}, "s1", str(cwd))


class GitCommandsTest(unittest.TestCase):
    def test_a_commit_is_found_with_its_repository(self):
        cases = {"git commit -m x": "C:/r", "git -C sub commit -m 'a && b'": "C:/r/sub",
                 "echo a && git commit -am x": "C:/r", "cd x; git -C C:/other commit": "C:/other"}
        for command, repo in cases.items():
            with self.subTest(command=command):
                self.assertEqual(GitCommands().translate(bash(command, "C:/r"))["git_commit"]["repo"], repo)

    def test_other_commands_are_no_commit(self):
        for command in ("git status", "gitk commit", "echo 'git commit'", "git log --grep commit"):
            with self.subTest(command=command):
                self.assertEqual(GitCommands().translate(bash(command, "C:/r")), {})


class GitRunTest(unittest.TestCase):
    def test_git_runs_from_a_list_and_reads_the_staged_files(self):
        repo = git_repo(self, {"a.py": "x\n"})
        (repo / "a.py").write_text("y\n", encoding="utf-8")
        git(repo, "add", "a.py")
        self.assertEqual(top(repo / "a.py").lower(), str(repo).replace("\\", "/").lower())
        self.assertEqual(list(staged(repo)), ["a.py"])
        with self.assertRaises(GitError):
            git(repo, "no-such-command")


PLAN = {"id": 7, "plan_id": "pd-1", "rev": 1, "root": "C:/r", "title": "t", "files": ["a.py"], "tests": ["test_a.py"]}


def kinds(commit, plan=PLAN):
    facts = {"plan": plan, "git_commit": {"repo": "C:/r"}, "commit_view": lambda repo, plan_row: commit}
    return [f.kind for f in CommitGate().detect(bash("git commit", "C:/r"), facts)]


class CommitGateTest(unittest.TestCase):
    def commit(self, receipt, staged_files):
        return {"repo": "C:/r", "staged": staged_files, "receipt": receipt}

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
        for kind in ("commit.unverified", "commit.changed", "commit.outside"):
            self.assertEqual(rules[kind]["verdict"], "refuse")
        names = {i["name"] for i in gear_block.ITEMS}
        self.assertLessEqual({"git_commands", "commit_gate"}, names)


class CommitFlowTest(unittest.TestCase):
    """Through the runner with a real repository: refused before verify, allowed after, delivered once committed."""

    def test_verify_then_commit_delivers_the_plan(self):
        claude_dir = copy_tree(self, {"project.json": json.dumps(
            {"name": "t", "recipe": "base", "verify": ["{python}", "-m", "unittest", "discover", "-s", "."]})})
        repo = git_repo(self, {"a.py": "X = 1\n", "test_a.py": "import unittest\n\nclass T(unittest.TestCase):\n"
                                                              "    def test_x(self):\n        pass\n"})
        port, runner = LedgerPort(claude_dir), build_runner(claude_dir)
        plan_id, _, q = port.present({"title": "t", "files": ["a.py"], "tests": ["test_a.py"]})
        runner.run(Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": q}], "answers": {q: "Duyệt"}},
                         "s1", str(repo)))
        (repo / "a.py").write_text("X = 2\n", encoding="utf-8")
        git(repo, "add", "a.py")
        commit = bash("git commit -m change", repo)
        self.assertEqual(runner.run(commit).verdict.decision, "refuse")
        self.assertIn("passed", verify(port, claude_dir, plan_id))
        self.assertEqual(runner.run(commit).verdict.decision, "allow")
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "change"], check=True)
        notes = runner.run(bash("git commit -m change", repo, "PostToolUse")).notes
        self.assertIn("delivered", " ".join(notes))
        self.assertIsNone(port.approved("s1"))
        row = port.ledger.one("SELECT commit_sha FROM rec_commits")
        self.assertEqual(row["commit_sha"], git(repo, "rev-parse", "HEAD").strip())


if __name__ == "__main__":
    unittest.main()
