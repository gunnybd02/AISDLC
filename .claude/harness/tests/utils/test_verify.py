"""h7.approval: verify runs the test command of the plan in force (its repo's, set by the server; else one the caller
gives) and keeps the receipt; a plan with no tests runs nothing and still keeps its receipt; a plan with tests and no
command is refused."""
import os
import unittest
import unittest.mock

from harness.utils.plan.verify import verify
from harness.assemble.engine.ports import LedgerPort
from harness.tests.e2e import copy_tree, git_repo

PLAN = {"title": "Add a greeting", "files": ["hello.py"], "tests": ["test_hello.py"]}


class VerifyBlockTest(unittest.TestCase):
    def approved(self, files, **items):
        """The port and the desk id of an approved plan on a new repository holding files."""
        port = LedgerPort(copy_tree(self))
        repo = git_repo(self, files)
        plan_id, _, _ = port.present({"title": "t", "files": list(files), "root": str(repo), **items})
        port.approve("s1", port.waiting()[0])
        return port, plan_id

    def test_a_file_changed_while_the_tests_ran_is_no_pass(self):
        port, plan_id = self.approved({"a.py": "X = 1\n"}, tests=[])
        touch = ["{python}", "-c", "open('a.py', 'a').write('# touched')"]
        self.assertIn("changed while", verify(port, touch, plan_id))
        self.assertEqual(port.receipt(port.approved("s1"))["ok"], 0)

    def test_a_plan_without_tests_verifies_with_nothing_to_run(self):
        port, plan_id = self.approved({"a.md": "one\n"})  # a docs plan: no tests, no command
        self.assertIn("passed", verify(port, [], plan_id))
        self.assertEqual(port.receipt(port.approved("s1"))["ok"], 1)

    def test_a_plan_with_tests_and_no_command_is_refused(self):
        port, plan_id = self.approved({"a.py": "X = 1\n", "test_a.py": ""}, tests=["test_a.py"])
        with self.assertRaises(ValueError) as caught:
            verify(port, [], plan_id)
        self.assertIn("no test command", str(caught.exception))

    def test_a_projects_tests_never_see_the_harness_in_force(self):
        """A child's verify once ran the harness's suite with HARNESS_HOME set, and its tests wrote to the live ledger."""
        check = "import os, sys; sys.exit(1 if any(os.environ.get(k) for k in %r) else 0)" % (
            ("HARNESS_HOME", "HARNESS_CODE", "HARNESS_SESSION"),)
        port, plan_id = self.approved({"a.md": "one\n"})
        live = {"HARNESS_HOME": "/live/.claude", "HARNESS_CODE": "/live/code", "HARNESS_SESSION": "s-live"}
        with unittest.mock.patch.dict(os.environ, live):
            self.assertIn("passed", verify(port, ["{python}", "-c", check], plan_id))

    def test_the_tests_get_no_ledger_and_no_copy_is_made(self):
        """The copy verify once made in HARNESS_DB was read by nothing; a test that records builds its own home."""
        check = "import os, sys, tempfile; sys.exit(1 if 'HARNESS_DB' in os.environ else 0)"
        port, plan_id = self.approved({"a.md": "one\n"})
        with unittest.mock.patch("tempfile.TemporaryDirectory") as made:
            self.assertIn("passed", verify(port, ["{python}", "-c", check], plan_id))
        made.assert_not_called()

    def test_the_test_command_of_the_plan_runs_before_the_one_given(self):
        port, plan_id = self.approved({"a.md": "one\n"}, verify=["{python}", "-c", "pass"])  # set by the server
        self.assertIn("passed", verify(port, ["{python}", "-c", "raise SystemExit(1)"], plan_id))


if __name__ == "__main__":
    unittest.main()
