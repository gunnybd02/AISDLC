"""h9.step-done: the harness commits a plan's change itself, only after a passing verify, only the plan's changed files,
never with a secret in them, and the plan is then delivered."""
import json
import unittest

from harness.assemble.engine.config import Config
from harness.assemble.engine.ports import LedgerPort
from harness.utils.contracts import YES
from harness.utils.git.run import git
from harness.utils.plan.approval import approvals
from harness.utils.plan.steps import StepError, step_done
from harness.utils.plan.verify import verify
from tests.e2e import copy_tree, git_repo

TEST_A = "import unittest\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\n"


class StepDoneTest(unittest.TestCase):
    def setUp(self):
        self.claude_dir = copy_tree(self, {"project.json": json.dumps(
            {"name": "t", "verify": ["{python}", "-m", "unittest", "discover", "-s", "."]})})
        self.repo = git_repo(self, {"a.py": "X = 1\n", "test_a.py": TEST_A, "other.py": "Y = 1\n"})
        self.port = LedgerPort(self.claude_dir)
        self.plan_id, _, q = self.port.present({"title": "t", "files": ["a.py"], "tests": ["test_a.py"],
                                                "root": str(self.repo)})
        approvals(self.port, "s1", {q: YES})

    def verify(self):
        return verify(self.port, Config.load(self.claude_dir).verify, self.plan_id)

    def write(self, name, text):
        (self.repo / name).write_text(text, encoding="utf-8")

    def refused(self, why, message="Set X"):
        with self.assertRaises(StepError) as caught:
            step_done(self.port, self.plan_id, message)
        self.assertIn(why, str(caught.exception))

    def test_a_verified_change_is_committed_alone_and_delivers_the_plan(self):
        self.write("a.py", "X = 2\n")
        self.write("other.py", "Y = 2\n")  # changed, staged even, but no file of the plan
        git(self.repo, "add", "other.py")
        self.verify()
        out = step_done(self.port, self.plan_id, "Set X")
        self.assertIn("delivered", out)
        self.assertEqual(git(self.repo, "show", "--name-only", "--format=%s", "HEAD").split(), ["Set", "X", "a.py"])
        self.assertIn("other.py", git(self.repo, "diff", "--cached", "--name-only"))
        self.assertIsNone(self.port.approved("s1"))
        self.refused("no approved plan")

    def test_no_commit_without_a_passing_verify(self):
        self.write("a.py", "X = 2\n")
        self.refused("no passing verify")
        self.write("test_a.py", TEST_A.replace("pass", "self.fail()"))
        self.verify()
        self.refused("no passing verify")

    def test_no_commit_of_a_file_changed_after_the_verify(self):
        self.write("a.py", "X = 2\n")
        self.verify()
        self.write("a.py", "X = 3\n")
        self.refused("changed since the verify: a.py")

    def test_no_commit_of_a_secret(self):
        self.write("a.py", "KEY = 'AKIA" + "ABCDEFGHIJKLMNOP'\n")
        self.verify()
        self.refused("a.py holds an AWS access key")
        self.assertEqual(git(self.repo, "rev-list", "--count", "HEAD").strip(), "1")

    def test_nothing_changed_is_nothing_to_commit(self):
        self.verify()
        self.refused("nothing to commit")

    def test_a_repository_that_moved_since_the_approval_is_refused(self):
        self.write("a.py", "X = 2\n")
        self.verify()
        git(self.repo, "commit", "--allow-empty", "-q", "-m", "moved")
        self.refused("moved since the approval")

    def test_an_empty_message_is_refused(self):
        self.refused("message is empty", message="  ")


if __name__ == "__main__":
    unittest.main()
