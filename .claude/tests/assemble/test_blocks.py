"""h7.approval: the plan block of the MCP server keeps a plan and answers the form question; a malformed plan is
refused with why."""
import unittest

from harness.assemble.build import action_table, items_of
from harness.assemble.ports import LedgerPort
from tests import CLAUDE_DIR, tree

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
        self.assertEqual(len(LedgerPort(self.root).waiting()), 1)
        self.assertIn("Add a greeting", self.call("plan_status"))

    def test_a_malformed_plan_is_refused_with_why(self):
        for plan in ({"files": ["a.py"]}, {"title": "x", "files": []}, {"title": "x", "files": ["/abs.py"]},
                     {"title": "x", "files": ["../out.py"]}, {"title": "x", "files": ["a.py"], "tests": "t.py"},
                     {"title": "x", "files": ["a.py"], "extra": 1}):
            with self.subTest(plan=plan):
                with self.assertRaises(ValueError):
                    self.call("plan_present", plan=plan)
        self.assertEqual(LedgerPort(self.root).waiting(), [])


if __name__ == "__main__":
    unittest.main()
