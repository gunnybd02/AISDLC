"""h18.close-and-settle: plan_close gives the close form with the facts of the ledger, only the user's answer closes
(delivered, abandoned) or keeps the plan open; plans_settle ends proven plans, and unproven plans of dead sessions only
after the user's Yes."""
import json
import re
import time
import unittest

from harness.assemble.engine.config import Config
from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.utils.contracts import YES, Event, Verdict
from harness.utils.plan import desk
from harness.utils.plan.approval import approvals
from harness.utils.plan.closing import close_question
from harness.utils.plan.life import settle
from harness.utils.plan.steps import step_done, step_skip
from harness.utils.plan.verify import verify
from tests.e2e import copy_tree, git_repo

TEST = "import unittest\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\n"
PLAN = {"title": "Set the value", "what": ["w"], "files": ["a.py", "b.py"], "tests": ["test_a.py"]}


class LifeTest(unittest.TestCase):
    def setUp(self):
        self.claude_dir = copy_tree(self, {"project.json": json.dumps(
            {"name": "t", "verify": ["{python}", "-m", "unittest", "discover", "-s", "."]})})
        self.repo = git_repo(self, {"a.py": "X = 1\n", "b.py": "Y = 1\n", "test_a.py": TEST})
        self.port = LedgerPort(self.claude_dir)
        self.port.touch_session("s1")

    def approve(self, sid="s1"):
        items = {**desk.normalize(desk.clean(PLAN)), "root": str(self.repo)}
        plan_id, _, q = self.port.present(items, sid=sid)
        approvals(self.port, sid, {q: YES})
        return plan_id

    def answer(self, question, label, sid="s1"):
        event = Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": question}]}, sid, str(self.repo))
        return Act(self.port).run(event, {"answers": {question: label}}, Verdict("allow"))

    def form(self, text):
        return re.search(r"exactly:\n(.+?)\nOptions", text, re.S).group(1)

    def test_the_close_form_gives_the_facts_and_only_the_answer_closes(self):
        plan_id = self.approve()
        step_skip(self.port, "s1", "done elsewhere")  # a skipped last step leaves the ticket in deliver
        q = self.form(close_question(self.port, "s1", summary="nothing to ship"))
        self.assertTrue(q.startswith(f'Đóng plan "Set the value" ({plan_id}) [t-'))
        for line in ("Summary: nothing to ship", "Commit: none", "untouched a.py, b.py, test_a.py", "Verify: none"):
            self.assertIn(line, q)
        self.assertIn("keeps plan", " ".join(self.answer(q, "Giữ mở")))
        self.assertEqual(self.port.ticket("s1")["state"], "open")
        self.assertIn("closed abandoned", " ".join(self.answer(q, "Bỏ plan")))
        ticket = self.port.ticket("s1")
        self.assertEqual((ticket["state"], ticket["closeReason"]), ("closed", "abandoned"))
        self.assertEqual(self.port.revision(plan_id)["event"], "dropped")
        logs = [json.loads(r["body"]) for r in self.port.rows("SELECT body FROM pl_logs")]
        self.assertIn("closure", [log["what"] for log in logs])
        with self.assertRaises(ValueError):
            close_question(self.port, "s1")  # no open ticket any more

    def test_the_close_form_refuses_wrong_arguments(self):
        self.approve()
        for summary, exceptions in (("two\nlines", None), ("x" * 201, None), (None, ["ok", "bad\nline"])):
            with self.subTest(summary=summary), self.assertRaises(ValueError):
                close_question(self.port, "s1", summary, exceptions)

    def test_settle_ends_proven_plans_and_drops_dead_ones_only_after_a_yes(self):
        delivered = self.approve()
        (self.repo / "a.py").write_text("X = 2\n", encoding="utf-8")
        verify(self.port, Config.load(self.claude_dir).verify, delivered)
        step_done(self.port, "s1", "Set X")
        self.assertIn("No plan is open", settle(self.port))  # step_done ended it already
        self.port.touch_session("s2")
        stale = self.approve("s2")
        self.assertIn(f"{stale} (no", settle(self.port))
        self.assertIn("unproven", settle(self.port, write=True))
        with self.assertRaises(ValueError) as caught:
            settle(self.port, drop=[stale])
        self.assertIn("still runs", str(caught.exception))
        self.port.write(lambda con, rec: con.execute("UPDATE sessions SET last_at = ? WHERE sid = 's2'",
                                                     (int(time.time() * 1000) - 7 * 3600 * 1000,)))
        asked = settle(self.port, drop=[stale])
        q = re.search(r"exactly: (.+?\?) Options", asked).group(1)
        self.assertEqual(self.port.revision(stale)["event"], "executing")
        self.answer(q, "Cho phép")
        self.assertIn("Dropped", settle(self.port, drop=[stale]))
        self.assertEqual(self.port.revision(stale)["event"], "dropped")
        self.assertEqual(self.port.ticket("s2")["closeReason"], "abandoned")


if __name__ == "__main__":
    unittest.main()
