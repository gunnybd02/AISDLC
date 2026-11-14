"""h7.approval: the plan block of the MCP server keeps a plan and answers the form question; a malformed plan is
refused with why."""
import json
import os
import re
import unittest

from harness.assemble.engine.config import Config
from harness.utils.plan.verify import verify
from harness.assemble.engine.build import items_of
from harness.assemble.engine.ports import LedgerPort
from tests import CLAUDE_DIR, tree
from tests.e2e import copy_tree, git_repo

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


if __name__ == "__main__":
    unittest.main()
