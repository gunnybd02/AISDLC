"""h7.approval: the plan block of the MCP server keeps a plan and answers the form question; a malformed plan is
refused with why."""
import json
import os
import re
import unittest

from harness.assemble.engine.config import Config
from harness.utils.plan.verify import verify
from harness.assemble.engine.build import items_of
from harness.assemble.engine.wire_mcp import action_table
from harness.assemble.engine.ports import LedgerPort
from tests import CLAUDE_DIR, tree
from tests.e2e import copy_tree, git_repo

PLAN = {"title": "Add a greeting", "files": ["hello.py"], "tests": ["test_hello.py"]}


class PlanBlockTest(unittest.TestCase):
    def setUp(self):
        self.root = tree(self, {})
        self.table = action_table(items_of(CLAUDE_DIR), self.root)

    def call(self, name, **args):
        action = self.table.action("plan", name)
        problem = action.problem(args)
        return problem or action.handler(**args)

    def test_plan_present_keeps_the_plan_and_gives_the_question_to_ask(self):
        out = self.call("plan_present", plan=PLAN)
        self.assertIn('Duyệt plan "Add a greeting" (pd-', out)
        self.assertIn("hello.py, test_hello.py", out)
        self.assertIn(os.getcwd().replace("\\", "/"), out)  # the root is the MCP server's folder, the project
        self.assertEqual(len(LedgerPort(self.root).waiting()), 1)
        self.assertIn("Add a greeting", self.call("plan_status"))

    def test_a_malformed_plan_is_refused_with_why(self):
        for plan in ({"files": ["a.py"]}, {"title": "x", "files": []}, {"title": "x", "files": ["/abs.py"]},
                     {"title": "x", "files": ["../out.py"]}, {"title": "x", "files": ["a.py"], "tests": "t.py"},
                     {"title": "x", "files": ["a.py"], "extra": 1}, {"title": "x", "files": [".git/hooks/pre-commit"]},
                     {"title": "x", "files": ["a/.GIT/config"]}, {"title": 'say "hi"', "files": ["a.py"]},
                     {"title": "x", "files": ["~/a.py"]}, {"title": "x", "files": ["%TEMP%/a.py"]},
                     {"title": "x", "files": ["a.py, b.py"]},
                     {"title": "x", "files": ["a.py"], "root": "C:/elsewhere"}):
            with self.subTest(plan=plan):
                with self.assertRaises(ValueError):
                    self.call("plan_present", plan=plan)
        self.assertEqual(LedgerPort(self.root).waiting(), [])

    def test_a_waiting_plan_takes_a_new_revision_by_its_id(self):
        first = self.call("plan_present", plan=PLAN)
        plan_id = re.search(r"\((pd-\w+) rev 1\)", first).group(1)
        second = self.call("plan_present", plan={**PLAN, "files": ["hello.py", "README.md"]}, plan_id=plan_id)
        self.assertIn(f"({plan_id} rev 2)", second)
        self.assertEqual([(w["plan_id"], w["rev"]) for w in LedgerPort(self.root).waiting()], [(plan_id, 2)])
        for bad in ("pd-nothere", "x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.call("plan_present", plan=PLAN, plan_id=bad)


if __name__ == "__main__":
    unittest.main()
