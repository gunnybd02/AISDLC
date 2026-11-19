"""Part 7, the end (utils/orchestra/ending.py): once every child's pull request is in the plan branch, land gives one
signed stop order per child that takes orders; form 2 asks the user once; its Allow opens the merge gate for exactly the
plan pull requests at their heads, and Deny changes nothing."""
import json
import re

from harness.assemble.engine.runner import Act
from harness.utils.contracts import Event, Verdict
from harness.utils.forge import merges
from harness.utils.orchestra import ending, land, orders, review
from harness.utils.plan import tickets
from harness.tests import tree
from harness.tests.utils.test_land import PlanGitHub
from harness.tests.utils.test_review import LOCKED_UNITS, LockedScenario, git

land.WAIT = 0


class EndingTest(LockedScenario):
    def landed(self):
        """The child handed back, checked, accepted; the parent's own step is done; land merged it into the plan
        branch and asks form 2. Its answer."""
        self.github = PlanGitHub(self.origin, tree(self, {}), {5: (f"orch/p{self.plan}/hello", f"plan/p{self.plan}")})
        self.hand_back()
        review.check(self.port, "s1", "hello", LOCKED_UNITS, [])
        review.accept(self.port, "s1", "hello", LOCKED_UNITS, self.github)
        self.port.write(lambda con, rec: tickets.save(con, {**self.port.ticket("s1"), "phase": "deliver"}))
        return land.land(self.port, "s1", LOCKED_UNITS, [], self.github)

    def answer(self, q, label):
        event = Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": q}]}, "s1", "/w")
        return Act(self.port).run(event, {"answers": {q: label}}, Verdict("allow"))

    def test_land_gives_one_stop_order_per_child_until_it_was_sent(self):
        """s6.end.stop-orders"""
        key = orders.key_for(self.port, "s1", "hello")
        text = self.landed()
        self.assertIn("Send hello its signed order (stop, round 1) now", text)
        self.assertIn("uploads its ledger copy and ends", text)
        call = json.loads(text[text.index(orders.SEND) + len(orders.SEND):].split(". Its harness")[0])
        (order,) = orders.parse(call["message"])
        self.assertEqual(orders.check(order, self.plan, "hello", orders.NO_ISSUE, orders.NO_SHA, key, 0), "")
        Act(self.port).run(Event("PostToolUse", orders.SEND, call, "s1", "/w", "sent"), {}, Verdict("allow"))
        self.assertNotIn("signed order (stop", land.land(self.port, "s1", LOCKED_UNITS, [], self.github))

    def test_form_2_allow_opens_the_merge_gate_and_deny_changes_nothing(self):
        """s6.end.form2"""
        text = self.landed()
        self.assertNotIn("signed order", text)  # a child without a key takes no orders
        q = re.search(r"exactly:\n(.+)\nOptions", text).group(1)
        head = git(self.origin, "rev-parse", f"plan/p{self.plan}").strip()
        gate = merges.code_of("o", "r", 6, head)
        self.assertIn(f"(PR #6 at {head[:12]})", q)
        self.assertEqual(self.answer(q, "Deny"), [])
        self.assertFalse(ending.allowed(self.port, self.port.ticket("s1")))
        self.assertFalse(merges.held(self.port, gate))
        stale = q.replace(q[q.index("[e"):q.index("]?")], "[e000000000000")
        self.answer(stale, "Allow")  # not the form the ticket holds
        self.assertFalse(merges.held(self.port, gate))
        notes = self.answer(q, "Allow")
        self.assertTrue(any(n.startswith("GATE: the user allows form 2") for n in notes))
        self.assertTrue(ending.allowed(self.port, self.port.ticket("s1")))
        self.assertTrue(merges.held(self.port, gate))
        self.assertEqual(self.port.ticket("s1")["state"], "open")  # nothing merged yet
