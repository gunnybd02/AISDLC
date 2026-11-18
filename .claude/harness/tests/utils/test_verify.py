"""h7.approval: the plan block of the MCP server keeps a plan and answers the form question; a malformed plan is
refused with why."""
import json
import os
import re
import unittest
import unittest.mock

from harness.assemble.engine.config import Config
from harness.utils.plan.verify import verify
from harness.assemble.engine.build import items_of
from harness.assemble.engine.ports import LedgerPort
from harness.tests import CLAUDE_DIR, tree
from harness.tests.e2e import copy_tree, git_repo

PLAN = {"title": "Add a greeting", "files": ["hello.py"], "tests": ["test_hello.py"]}


class VerifyBlockTest(unittest.TestCase):
    def test_a_file_changed_while_the_tests_ran_is_no_pass(self):
        claude_dir = copy_tree(self, {"project.json": json.dumps({"name": "t", "verify": [
            "{python}", "-c", "open('a.py', 'a').write('# touched')"]})})
        repo = git_repo(self, {"a.py": "X = 1\n"})
        port = LedgerPort(claude_dir)
        plan_id, _, q = port.present({"title": "t", "files": ["a.py"], "tests": [], "root": str(repo)})
        port.approve("s1", port.waiting()[0])
        self.assertIn("changed while", verify(port, Config.load(claude_dir).verify, plan_id))
        self.assertEqual(port.receipt(port.approved("s1"))["ok"], 0)

    def test_a_plan_without_tests_verifies(self):
        claude_dir = copy_tree(self, {"project.json": json.dumps({"name": "t", "verify": ["{python}", "-c", "pass"]})})
        repo = git_repo(self, {"a.md": "one\n"})
        port = LedgerPort(claude_dir)
        plan_id, _, q = port.present({"title": "t", "files": ["a.md"], "root": str(repo)})  # a docs plan: no tests
        port.approve("s1", port.waiting()[0])
        self.assertIn("passed", verify(port, Config.load(claude_dir).verify, plan_id))
        self.assertEqual(port.receipt(port.approved("s1"))["ok"], 1)

    def test_a_projects_tests_never_see_the_harness_in_force(self):
        """A child's verify once ran the harness's suite with HARNESS_HOME set, and its tests wrote to the live ledger."""
        check = "import os, sys; sys.exit(1 if any(os.environ.get(k) for k in %r) else 0)" % (
            ("HARNESS_HOME", "HARNESS_CODE", "HARNESS_SESSION"),)
        claude_dir = copy_tree(self, {"project.json": json.dumps({"name": "t", "verify": ["{python}", "-c", check]})})
        repo = git_repo(self, {"a.md": "one\n"})
        port = LedgerPort(claude_dir)
        plan_id, _, q = port.present({"title": "t", "files": ["a.md"], "root": str(repo)})
        port.approve("s1", port.waiting()[0])
        live = {"HARNESS_HOME": "/live/.claude", "HARNESS_CODE": "/live/code", "HARNESS_SESSION": "s-live"}
        with unittest.mock.patch.dict(os.environ, live):
            self.assertIn("passed", verify(port, Config.load(claude_dir).verify, plan_id))


    def test_the_tests_get_no_ledger_and_no_copy_is_made(self):
        """The copy verify once made in HARNESS_DB was read by nothing; a test that records builds its own home."""
        check = "import os, sys, tempfile; sys.exit(1 if 'HARNESS_DB' in os.environ else 0)"
        claude_dir = copy_tree(self, {"project.json": json.dumps({"name": "t", "verify": ["{python}", "-c", check]})})
        repo = git_repo(self, {"a.md": "one\n"})
        port = LedgerPort(claude_dir)
        plan_id, _, _ = port.present({"title": "t", "files": ["a.md"], "root": str(repo)})
        port.approve("s1", port.waiting()[0])
        with unittest.mock.patch("tempfile.TemporaryDirectory") as made:
            self.assertIn("passed", verify(port, Config.load(claude_dir).verify, plan_id))
        made.assert_not_called()

    def test_the_test_command_of_the_plan_runs_before_the_one_of_the_config(self):
        claude_dir = copy_tree(self, {"project.json": json.dumps({"name": "t", "verify": ["{python}", "-c",
                                                                                            "raise SystemExit(1)"]})})
        repo = git_repo(self, {"a.md": "one\n"})
        port = LedgerPort(claude_dir)
        plan_id, _, q = port.present({"title": "t", "files": ["a.md"], "root": str(repo),
                                      "verify": ["{python}", "-c", "pass"]})  # set by the server from the plan's repo
        port.approve("s1", port.waiting()[0])
        self.assertIn("passed", verify(port, Config.load(claude_dir).verify, plan_id))


if __name__ == "__main__":
    unittest.main()
