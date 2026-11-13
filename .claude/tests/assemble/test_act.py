"""h7.approval: only the user's "Duyệt" in the form, to the question of the waiting revision, approves a plan; the
ledger keeps the revision, the approval and its events."""
import json
import unittest

import harness.hooks as hooks_block
from harness.assemble.engine.act import Act
from harness.assemble.engine.ports import LedgerPort, question
from harness.hooks.forms import Answers
from harness.utils.contracts import Event, Finding, Verdict
from harness.utils.ledger.recorder import Recorder
from tests import tree

PLAN = {"title": "Add a greeting", "files": ["hello.py"], "tests": ["test_hello.py"], "root": "C:/repo"}


def answered(q, label, how="input"):
    """A PostToolUse of AskUserQuestion as Claude Code sends it, the answer in one of the places it may be."""
    tool_input = {"questions": [{"question": q, "options": [{"label": "Duyệt"}, {"label": "Sửa plan"}]}]}
    response = None
    if how == "input":
        tool_input["answers"] = {q: label}
    elif how == "json":
        response = json.dumps({"answers": {q: label}})
    else:
        response = f'User has answered your questions: "{q}"="{label}". You can now continue.'
    return Event("PostToolUse", "AskUserQuestion", tool_input, "s1", "C:/repo", response)


class ApprovalTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(tree(self, {}))
        self.plan_id, self.rev, self.q = self.port.present(PLAN)

    def act(self, event):
        facts = Answers().translate(event)
        return Act(self.port).run(event, facts, Verdict("allow"))

    def test_present_keeps_the_revision_and_gives_the_form_question(self):
        self.assertEqual(self.q, question(PLAN, self.plan_id, 1))
        self.assertIn("hello.py, test_hello.py", self.q)
        self.assertIn("C:/repo", self.q)
        self.assertEqual([w["question"] for w in self.port.waiting()], [self.q])
        self.assertIsNone(self.port.approved("s1"))

    def test_duyet_in_the_form_approves_the_plan_for_the_session(self):
        for how in ("input", "json", "text"):
            with self.subTest(how=how):
                port = LedgerPort(tree(self, {}))
                plan_id, _, q = port.present(PLAN)
                notes = Act(port).run(answered(q, "Duyệt", how), Answers().translate(answered(q, "Duyệt", how)),
                                      Verdict("allow"))
                plan = port.approved("s1")
                self.assertEqual((plan["plan_id"], plan["root"], plan["files"]), (plan_id, "C:/repo", ["hello.py"]))
                self.assertIn("approved", " ".join(notes))
                self.assertEqual(port.waiting(), [])

    def test_another_answer_or_another_question_approves_nothing(self):
        notes = self.act(answered(self.q, "Sửa plan"))
        self.assertIsNone(self.port.approved("s1"))
        self.assertIn("did not approve", " ".join(notes))
        self.act(answered(question(PLAN, self.plan_id, 2), "Duyệt"))
        self.act(answered(question({**PLAN, "title": "Other"}, self.plan_id, 1), "Duyệt"))
        self.act(answered(question({**PLAN, "files": ["other.py"]}, self.plan_id, 1), "Duyệt"))
        self.assertIsNone(self.port.approved("s1"))

    def test_only_the_newest_revision_can_be_approved(self):
        _, rev2, q2 = self.port.present(PLAN, self.plan_id)
        self.assertEqual(rev2, 2)
        self.act(answered(self.q, "Duyệt"))
        self.assertIsNone(self.port.approved("s1"))
        self.act(answered(q2, "Duyệt"))
        self.assertEqual(self.port.approved("s1")["rev"], 2)

    def test_a_new_approval_takes_the_place_of_the_old_one(self):
        self.act(answered(self.q, "Duyệt"))
        plan_id2, _, q2 = self.port.present({**PLAN, "title": "Second"})
        self.act(answered(q2, "Duyệt"))
        self.assertEqual(self.port.approved("s1")["plan_id"], plan_id2)

    def test_the_ledger_keeps_revisions_events_and_a_chained_plan_row(self):
        self.act(answered(self.q, "Duyệt"))
        ledger = self.port.ledger
        events = [e["event"] for e in ledger.all("SELECT event FROM pl_plan_events WHERE plan_id = ? ORDER BY n",
                                                 (self.plan_id,))]
        self.assertEqual(events, ["waiting", "approved"])
        self.assertEqual(ledger.one("SELECT status FROM rec_plans")["status"], "approved")
        self.assertTrue(Recorder.chain_ok(ledger, "rec_plans"))

    def test_a_tool_call_with_findings_is_recorded_as_a_rule_decision(self):
        event = Event("PreToolUse", "Write", {"file_path": "x"}, "s1", "C:/repo")
        Act(self.port).run(event, {}, Verdict("refuse", "why", (Finding("plan.none", "x"),)))
        row = self.port.ledger.one("SELECT rule, verdict, tool FROM act_rule_decisions")
        self.assertEqual(row, {"rule": "plan.none", "verdict": "deny", "tool": "Write"})

    def test_reading_never_creates_the_ledger(self):
        root = tree(self, {})
        self.assertIsNone(LedgerPort(root).approved("s1"))
        self.assertFalse((root / "state" / "harness.db").exists())

    def test_hooks_declares_the_answer_translator(self):
        self.assertIn("answers", {i["name"] for i in hooks_block.ITEMS})


if __name__ == "__main__":
    unittest.main()
