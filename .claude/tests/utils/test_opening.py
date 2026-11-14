"""h7.opening: the user's approval opens the plan in one transaction: plan number, behaviours with tests, ticket,
approval state, events and logs; a word in the chat opens nothing."""
import json
import unittest
from unittest import mock

from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.hooks.io import HookIO
from harness.utils.contracts import YES, Event, Verdict
from harness.utils.plan import opening
from harness.utils.plan.approval import approvals
from tests import tree

ITEMS = {"title": "Ship the parser", "what": ["w"], "files": ["p.py"], "tests": ["test_p.py"], "root": "/r",
         "behaviors": [{"id": "s1.reads", "what": "reads", "how": "h", "why": "y", "test": "test_p.py", "step": 1},
                       {"id": "s1.later", "what": "later", "how": "h", "why": "y", "step": 1}],
         "steps": [{"commit": "Add parser", "points": ["p"], "files": ["p.py"]}]}


class OpeningTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(tree(self, {}))
        self.plan_id, _, self.q = self.port.present(ITEMS, sid="s1")

    def rows(self, sql):
        return [dict(r) for r in self.port.rows(sql)]

    def test_present_keeps_the_pending_block_and_the_tool(self):
        body = json.loads(self.rows("SELECT body FROM pl_approval WHERE sid = 's1'")[0]["body"])
        self.assertIn("## Plan: Ship the parser", body["pending"])
        self.assertEqual((body["tool"]["planId"], body["tool"]["rev"]), (self.plan_id, 1))

    def test_the_approval_writes_every_row_of_the_opening(self):
        approvals(self.port, "s1", {self.q: YES})
        (plan,) = self.rows("SELECT id, sid, status FROM rec_plans")
        self.assertEqual((plan["sid"], plan["status"]), ("s1", "approved"))
        behaviors = self.rows("SELECT id, op, plan_id FROM pl_behaviors")
        self.assertEqual(behaviors, [{"id": "s1.reads", "op": "add", "plan_id": plan["id"]}])  # one with a test only
        ticket = self.port.ticket("s1")
        self.assertEqual((ticket["phase"], ticket["plan"]["commit"], ticket["plan"]["id"]), ("execute", "", plan["id"]))
        body = json.loads(self.rows("SELECT body FROM pl_approval WHERE sid = 's1'")[0]["body"])
        self.assertEqual((body["open"], body["pending"], body["tool"], body["approved"]["plan"]),
                         (True, None, None, plan["id"]))
        events = [r["event"] for r in self.rows(f"SELECT event FROM pl_plan_events WHERE plan_id = '{self.plan_id}' "
                                                "ORDER BY n")]
        self.assertEqual(events, ["waiting", "approved", "executing"])
        logs = [json.loads(r["body"])["what"] for r in self.rows("SELECT body FROM pl_logs ORDER BY at, rowid")]
        self.assertEqual(logs, ["gate-open", "form"])
        self.assertEqual([r["text"] for r in self.rows("SELECT text FROM pl_plan_feedback")], [YES])

    def test_the_opening_is_one_transaction(self):
        with mock.patch("harness.utils.plan.tickets.open_plan", side_effect=RuntimeError("down")):
            with self.assertRaises(RuntimeError):
                approvals(self.port, "s1", {self.q: YES})
        for table in ("rec_plans", "pl_behaviors", "pl_tickets", "pl_logs"):
            with self.subTest(table=table):
                self.assertEqual(self.rows(f"SELECT 1 FROM {table}"), [])

    def test_the_same_approval_again_reuses_its_plan_number(self):
        waiting = self.port.waiting()[0]
        first = self.port.write(lambda con, rec: opening.open_plan(con, rec, "s1", waiting, None))
        again = self.port.write(lambda con, rec: opening.open_plan(con, rec, "s1", waiting, None))
        self.assertEqual(first, again)
        self.assertEqual(len(self.rows("SELECT 1 FROM rec_plans")), 1)

    def test_drop_clears_what_waits(self):
        self.port.drop(self.plan_id, 1, "s1")
        body = json.loads(self.rows("SELECT body FROM pl_approval WHERE sid = 's1'")[0]["body"])
        self.assertEqual((body["pending"], body["tool"]), (None, None))


class PromptTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(tree(self, {}))

    def prompt(self, text):
        event = HookIO.read(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": text, "session_id": "s1"}))
        return Act(self.port).run(event, {}, Verdict("allow"))

    def test_a_word_in_the_chat_approves_no_plan(self):
        _, _, q = self.port.present(ITEMS, sid="s1")
        for word in ("ok", "Duyệt!", "đồng ý", "LGTM", "làm đi"):
            with self.subTest(word=word):
                self.assertIn("only the answer in the form approves it", " ".join(self.prompt(word)))
        self.assertIsNone(self.port.approved("s1"))
        self.assertEqual(self.prompt("ok, but rename the file first"), [])

    def test_no_plan_waits_no_note(self):
        self.assertEqual(self.prompt("ok"), [])

    def test_each_prompt_is_kept_and_a_long_one_cut(self):
        self.prompt("x" * 2500)
        self.prompt("short")
        rows = [dict(r) for r in self.port.rows("SELECT n, chars, cut, length(text) AS kept FROM pl_prompts ORDER BY n")]
        self.assertEqual(rows, [{"n": 1, "chars": 2500, "cut": 1, "kept": 2000}, {"n": 2, "chars": 5, "cut": 0, "kept": 5}])
        self.assertEqual(self.port.session(), "s1")


if __name__ == "__main__":
    unittest.main()
