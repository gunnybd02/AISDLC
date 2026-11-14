"""h14.git-block: git through the harness. A free branch runs at once; on a protected one the user accepts the command
in a form first, kept in SQL, and one acceptance is one run; git commit never runs here. Every run is kept."""
import json
import re
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.utils.contracts import YES, Event, Verdict
from harness.utils.git.run import git
from tests.e2e import copy_tree, git_repo
from tests.mcp import caller


class GitBlockTest(unittest.TestCase):
    def setUp(self):
        self.claude_dir = copy_tree(self)
        self.run = caller(self.claude_dir)
        self.ledger = LedgerPort(self.claude_dir)
        self.repo = git_repo(self, {"a.py": "X = 1\n"})  # on branch work; main is protected
        git(self.repo, "branch", "main")

    def git(self, *words):
        return self.run("git", "run", repo=str(self.repo), args=list(words))

    def answer(self, question, label=YES):
        """The user's answer to the form, as the hook's PostToolUse gives it to Act."""
        event = Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": question}]}, "s1", str(self.repo))
        return Act(self.ledger).run(event, {"answers": {question: label}}, Verdict("allow"))

    def runs(self):
        rows = self.ledger.rows("SELECT ok, exit, reason, command, linked_to FROM pl_git_runs ORDER BY at, rowid")
        return [tuple(r[k] for k in ("ok", "exit", "reason", "command", "linked_to")) for r in rows]

    def test_a_free_branch_runs_at_once_and_is_kept(self):
        out = self.git("reset", "--hard", "HEAD")
        self.assertTrue(out.text.startswith("git reset --hard HEAD: exit 0"), out.text)
        ((ok, code, reason, command, _),) = self.runs()
        self.assertEqual((ok, code, reason, json.loads(command)["args"]), (1, 0, "", ["reset", "--hard", "HEAD"]))

    def test_a_protected_branch_runs_only_after_the_users_word_once(self):
        git(self.repo, "checkout", "-q", "main")
        asked = self.git("reset", "--hard", "HEAD")
        self.assertFalse(asked.is_error)
        q = re.search(r"exactly: (.+?\?) Options", asked.text).group(1)
        self.assertIn("reset --hard HEAD", q)
        self.assertEqual(self.runs(), [])
        self.assertEqual(self.answer(q, "Không"), [])  # another answer accepts nothing
        self.assertIn("exactly:", self.git("reset", "--hard", "HEAD").text)
        self.assertIn("accepted", " ".join(self.answer(q)))
        done = self.git("reset", "--hard", "HEAD")
        self.assertIn("exit 0 (accepted by the user)", done.text)
        ((ok, _, reason, _, code),) = self.runs()
        self.assertIn("git.reset_hard", reason)
        self.assertIn(code, q)
        self.assertEqual(self.ledger.rows("SELECT used FROM pl_asks WHERE key = ?", (code,))[0]["used"], 1)
        self.assertIn("exactly:", self.git("reset", "--hard", "HEAD").text)  # one word, one run

    def test_an_acceptance_holds_for_exactly_its_command(self):
        git(self.repo, "checkout", "-q", "main")
        q = re.search(r"exactly: (.+?\?) Options", self.git("reset", "--hard", "HEAD").text).group(1)
        self.answer(q)
        self.assertIn("exactly:", self.git("reset", "--hard", "HEAD~0").text)

    def test_a_commit_never_runs_here(self):
        out = self.git("commit", "-m", "x")
        self.assertTrue(out.is_error)
        self.assertIn("step_done", out.text)
        self.assertEqual(self.runs(), [])

    def test_wrong_arguments_are_refused(self):
        for words in ([], ["git", "status"], ["status", ""]):
            with self.subTest(words=words):
                self.assertTrue(self.run("git", "run", repo=str(self.repo), args=words).is_error)
        self.assertTrue(self.run("git", "run", repo=str(self.repo / "nope"), args=["status"]).is_error)


if __name__ == "__main__":
    unittest.main()
