"""h9.commit-gate: a commit goes through only when the plan's verify passed and no staged file changed since, and only
with files the plan names; a commit that went through is kept and delivers the plan."""
import json
import subprocess
import unittest

import harness.gear as gear_block
from harness.assemble.engine.config import Config
from harness.utils.plan.closing import close_facts
from harness.utils.plan.verify import verify
from harness.assemble.engine.build import build_runner
from harness.assemble.engine.ports import LedgerPort
from harness.gear.decide.arbiter import Decide
from harness.gear.translate.git import GitCommands
from harness.utils.contracts import Event
from harness.utils.git.facts import staged, top
from harness.utils.git.run import GitError, git
from harness.tests import CLAUDE_DIR, tree
from harness.tests.e2e import copy_tree, git_repo


def bash(command, cwd, kind="PreToolUse"):
    return Event(kind, "Bash", {"command": command}, "s1", str(cwd))


def commit_fact(command):
    return GitCommands().translate(bash(command, "C:/r")).get("git_commit")


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
                                                                 "answers": {q: "Approve"}}, "s1", str(self.repo)))

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
                                                                 "answers": {q: "Approve"}}, "s2", str(empty)))
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
        self.assertEqual(runner.run(commit).verdict.decision, "refuse")  # from the shell never, verified or not
        # a commit made some other way is still judged by what it holds: exactly the verified change delivers
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "change"], check=True)
        notes = runner.run(bash("git commit -m change", repo, "PostToolUse")).notes
        self.assertIn("delivered", " ".join(notes))
        self.assertIsNone(port.approved("s1"))
        row = port.ledger.one("SELECT commit_sha FROM rec_commits")
        self.assertEqual(row["commit_sha"], git(repo, "rev-parse", "HEAD").strip())


class ClosureTest(unittest.TestCase):
    """Closing a plan keeps one closure row (pl_plan_closures): the choice, the facts, what does not match."""

    def setUp(self):
        from harness.utils.plan import desk
        from harness.utils.plan.approval import approvals
        from harness.utils.contracts import YES
        self.claude_dir = copy_tree(self, {"project.json": json.dumps(
            {"name": "t", "verify": ["{python}", "-m", "unittest", "discover", "-s", "."]})})
        self.repo = git_repo(self, {"a.py": "X = 1\n", "test_a.py": "import unittest\n\nclass T(unittest.TestCase):\n"
                                                                   "    def test_x(self):\n        pass\n"})
        self.port = LedgerPort(self.claude_dir)
        items = {**desk.normalize(desk.clean({"title": "Set the value", "what": ["w"], "files": ["a.py"],
                                              "tests": ["test_a.py"]})), "root": str(self.repo)}
        self.plan_id, _, q = self.port.present(items, sid="s1")
        approvals(self.port, "s1", {q: YES})

    def closures(self):
        return [dict(r) for r in self.port.rows("SELECT sid, plan_id, ticket, plan_no, choice, summary, facts, mismatches "
                                                "FROM pl_plan_closures ORDER BY at, rowid")]

    def answer(self, label, summary=None):
        from harness.utils.plan.closing import close_answers, close_question
        text = close_question(self.port, "s1", summary)
        question = text.split("exactly:\n", 1)[1].rsplit("\nOptions:", 1)[0]
        return close_answers(self.port, "s1", {question: label})

    def test_an_answer_that_closes_nothing_keeps_no_row_and_a_drop_keeps_one(self):
        from harness.utils.plan.closing import ABANDON_LABEL, KEEP_LABEL
        self.assertIn("keeps plan", self.answer(KEEP_LABEL)[0])
        self.assertEqual(self.closures(), [])
        ticket = self.port.ticket("s1")
        self.assertIn("closed abandoned", self.answer(ABANDON_LABEL, "not needed any more")[0])
        row = self.closures()[0]
        self.assertEqual((row["sid"], row["plan_id"], row["ticket"], row["plan_no"], row["choice"], row["summary"]),
                         ("s1", self.plan_id, ticket["id"], ticket["plan"]["id"], "abandoned", "not needed any more"))
        self.assertIn("Verify: none", json.loads(row["facts"])["lines"])  # the facts the user saw at the close
        self.assertEqual(row["mismatches"], "[]")
        self.assertEqual(len(self.closures()), 1)

    def test_the_last_step_of_a_home_plan_keeps_its_closure_and_a_commit_the_ledger_lacks_is_a_mismatch(self):
        from harness.assemble.engine.ticket_port import closure
        from harness.utils.plan.steps import step_done
        (self.repo / "a.py").write_text("X = 2\n", encoding="utf-8")
        verify(self.port, Config.load(self.claude_dir).verify, self.plan_id)
        self.assertIn("plan is delivered", step_done(self.port, "s1", "Set X"))
        row = self.closures()[0]
        self.assertEqual((row["choice"], row["mismatches"]), ("delivered", "[]"))  # its commit is in the ledger
        facts = json.loads(row["facts"])
        self.assertEqual(facts["lines"], ["Closed by its last step, with no form."])
        self.assertEqual(len(facts["commits"]), 1)
        ticket = {**self.port.ticket("s1"), "commits": ["f" * 40]}  # a commit the ticket declares and the ledger lacks
        self.port.write(lambda con, rec: closure(con, "s1", ticket, "delivered", []))
        self.assertEqual(json.loads(self.closures()[1]["mismatches"]),
                         ["commit ffffffffffff: declared by the ticket, not in the ledger"])


class NoTestsPlanTest(unittest.TestCase):
    def test_the_close_form_counts_a_plan_without_tests(self):
        claude_dir = copy_tree(self, {"project.json": json.dumps({"name": "t", "verify": ["{python}", "-c", "pass"]})})
        repo = git_repo(self, {"a.md": "one\n"})
        port = LedgerPort(claude_dir)
        port.present({"title": "t", "files": ["a.md"], "root": str(repo)})  # a docs plan: no tests
        port.approve("s1", port.waiting()[0])
        lines = close_facts(port, port.ticket("s1"), port.approved("s1"))
        self.assertIn("untouched a.md", " ".join(lines))


if __name__ == "__main__":
    unittest.main()
