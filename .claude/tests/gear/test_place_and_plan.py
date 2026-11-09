"""h8.edit-gate: a file is edited only under an approved plan and only if the plan names it; the harness's own state is
never edited; the model never fills in the answers of a form."""
import json
import unittest

import harness.gear as gear_block
from harness.assemble.build import build_runner
from harness.assemble.ports import LedgerPort, question
from harness.gear.decide import Decide
from harness.gear.detect_plan import PlanGate
from harness.gear.translate_place import Places
from harness.utils.contracts import Event
from tests import CLAUDE_DIR
from tests.e2e import copy_tree

ROOT = "C:/repo"
PLAN = {"id": 1, "plan_id": "pd-1", "rev": 1, "root": ROOT, "title": "t", "files": ["src/a.py"], "tests": ["test_a.py"]}
STATE = "C:/harness/.claude/state"


def write(path, tool="Write", cwd=ROOT):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return Event("PreToolUse", tool, {key: path}, "s1", cwd)


def kinds(event, plan=PLAN):
    facts = {**Places().translate(event), "plan": plan, "state_dir": STATE}
    return [f.kind for f in PlanGate().detect(event, facts)]


class PlacesTest(unittest.TestCase):
    def test_the_editing_tools_give_absolute_paths(self):
        for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            with self.subTest(tool=tool):
                self.assertEqual(Places().translate(write("src/a.py", tool))["writes"], ["C:/repo/src/a.py"])
        self.assertEqual(Places().translate(Event("PreToolUse", "Read", {"file_path": "x"})), {})


class PlanGateTest(unittest.TestCase):
    def test_an_edit_without_an_approved_plan_is_refused(self):
        self.assertEqual(kinds(write("C:/repo/src/a.py"), plan=None), ["plan.none"])

    def test_an_edit_of_a_file_outside_the_plan_is_refused(self):
        for path in ("C:/repo/src/b.py", "C:/other/src/a.py", "C:/repo/src/../../x.py"):
            with self.subTest(path=path):
                self.assertEqual(kinds(write(path)), ["plan.outside"])

    def test_an_edit_of_a_plan_file_or_test_passes(self):
        for path in ("C:/repo/src/a.py", "c:\\REPO\\src\\a.py", "test_a.py"):
            with self.subTest(path=path):
                self.assertEqual(kinds(write(path)), [])

    def test_the_state_of_the_harness_is_never_edited(self):
        self.assertEqual(kinds(write(STATE + "/pause.json")), ["write.state"])
        self.assertEqual(kinds(write(STATE + "/harness.db"), plan=None), ["write.state"])

    def test_a_form_the_model_answered_itself_is_refused(self):
        event = Event("PreToolUse", "AskUserQuestion", {"questions": [{"question": "q"}], "answers": {"q": "Duyệt"}})
        facts = {"form_prefilled": ["q"], "plan": None}
        self.assertEqual([f.kind for f in PlanGate().detect(event, facts)], ["form.prefilled"])


class RulesTest(unittest.TestCase):
    def test_each_finding_of_the_gate_is_refused_by_a_rule(self):
        decide = Decide.load(CLAUDE_DIR)
        for kind in ("plan.none", "plan.outside", "write.state", "form.prefilled"):
            with self.subTest(kind=kind):
                self.assertEqual(decide.rules[kind]["verdict"], "refuse")

    def test_gear_declares_the_gate_and_the_recipe_runs_it(self):
        names = {i["name"] for i in gear_block.ITEMS}
        self.assertLessEqual({"places", "plan_gate"}, names)
        recipe = json.loads((CLAUDE_DIR / "harness" / "assemble" / "recipes" / "base.json").read_text(encoding="utf-8"))
        self.assertIn("plan_gate", recipe["detectors"])


class EditGateRunTest(unittest.TestCase):
    def test_the_gate_opens_only_after_the_form(self):
        claude_dir = copy_tree(self)
        port = LedgerPort(claude_dir)
        runner = build_runner(claude_dir)
        edit = write("C:/repo/src/a.py")
        self.assertEqual(runner.run(edit).verdict.decision, "refuse")
        plan_id, rev, q = port.present({"title": "t", "files": ["src/a.py"], "tests": []})
        answer = Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": q}], "answers": {q: "Duyệt"}},
                       "s1", ROOT)
        runner.run(answer)
        self.assertEqual(runner.run(edit).verdict.decision, "allow")
        self.assertEqual(runner.run(write("C:/repo/src/b.py")).verdict.decision, "refuse")
        self.assertEqual(question("t", plan_id, rev), q)


if __name__ == "__main__":
    unittest.main()
