"""h15.ticket: a ticket runs a plan from its approval to its close; approved_plan is the one rule for a plan in force."""
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.utils.contracts import YES
from harness.utils.plan import tickets
from harness.utils.plan.approval import approvals
from tests import tree


def plan(n, draft):
    return {"id": n, "plan_id": draft, "rev": 1, "base": "abc", "title": "t", "files": ["a.py"], "tests": [], "root": "/r"}


class TicketTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(tree(self, {}))

    def write(self, change):
        return self.port.write(lambda con, rec: change(con))

    def test_an_approval_opens_a_ticket_in_execute(self):
        ticket = self.write(lambda con: tickets.open_plan(con, "s1", plan(7, "pd-a")))
        self.assertEqual((ticket["state"], ticket["phase"], ticket["draft"], ticket["rootId"]), ("open", "execute", "pd-a", 7))
        self.assertTrue(ticket["id"].startswith("t-"))
        self.assertEqual(self.port.approved("s1")["id"], 7)
        self.assertIsNone(self.port.approved("s2"))

    def test_a_revision_keeps_its_ticket_and_root(self):
        first = self.write(lambda con: tickets.open_plan(con, "s1", plan(7, "pd-a")))
        second = self.write(lambda con: tickets.open_plan(con, "s1", {**plan(8, "pd-a"), "rev": 2}))
        self.assertEqual((second["id"], second["rootId"], second["plan"]["id"]), (first["id"], 7, 8))
        self.assertEqual(len(self.port.rows("SELECT 1 FROM pl_tickets")), 1)

    def test_another_plan_supersedes_the_open_one_and_carries_its_work(self):
        first = self.write(lambda con: tickets.open_plan(con, "s1", plan(7, "pd-a")))
        self.write(lambda con: tickets.save(con, {**first, "commits": ["c1"], "doneSteps": [1]}))
        second = self.write(lambda con: tickets.open_plan(con, "s1", plan(9, "pd-b")))
        old = self.port.rows("SELECT body FROM pl_tickets WHERE id = ?", (first["id"],))[0]["body"]
        self.assertIn('"closeReason": "superseded"', old)
        self.assertEqual((second["priorCommits"], second["doneSteps"], second["spentPlan"]), (["c1"], [1], 7))
        self.assertEqual(self.port.approved("s1")["plan_id"], "pd-b")
        self.assertIsNone(self.port.approved_plan("pd-a"))

    def test_a_delivered_ticket_holds_no_plan(self):
        ticket = self.write(lambda con: tickets.open_plan(con, "s1", plan(7, "pd-a")))
        closed = self.write(lambda con: tickets.deliver(con, ticket, "sha1"))
        self.assertEqual((closed["state"], closed["closeReason"], closed["commits"]), ("closed", "delivered", ["sha1"]))
        self.assertIsNone(self.port.approved("s1"))
        reopened = self.write(lambda con: tickets.open_plan(con, "s1", plan(9, "pd-b")))
        self.assertNotEqual(reopened["id"], ticket["id"])

    def test_approved_plan_is_the_one_rule(self):
        good = {"state": "open", "phase": "execute", "plan": {"type": "ApprovedPlan"}}
        self.assertIsNotNone(tickets.approved_plan(good))
        for bad in (None, {**good, "state": "closed"}, {**good, "phase": "prepare"}, {**good, "plan": {"type": "x"}},
                    {**good, "plan": None}):
            with self.subTest(bad=bad):
                self.assertIsNone(tickets.approved_plan(bad))

    def test_the_form_answer_opens_the_ticket(self):
        plan_id, _, q = self.port.present({"title": "t", "files": ["a.py"], "tests": [], "root": "/r"})
        approvals(self.port, "s1", {q: YES})
        ticket = self.port.ticket("s1")
        self.assertEqual((ticket["draft"], ticket["phase"]), (plan_id, "execute"))


if __name__ == "__main__":
    unittest.main()
