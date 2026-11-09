"""h10.pause: only the user's "Duyệt" in the form 'Tắt guard N phút: why?' pauses the guards, for N minutes at most
120, with a trace; it works when the harness itself is broken, and the model can neither answer the form nor ask for
the pause around a broken harness."""
import json
import time
import unittest

from harness.assemble.build import action_table, items_of
from tests import CLAUDE_DIR, tree
from tests.e2e import copy_tree, run

BROKEN = {"harness/assemble/build.py": "raise RuntimeError('broken')\n"}
Q = "Tắt guard 15 phút: sửa harness?"


def hook(root, payload):
    return run(root / "entry" / "hook.py", json.dumps(payload))


def write_call():
    return {"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {"file_path": "C:/x/a.py"},
            "session_id": "s1", "cwd": "C:/x"}


def form(question, kind="PostToolUse", answer=None, prefilled=False):
    tool_input = {"questions": [{"question": question, "options": [{"label": "Duyệt"}, {"label": "Không"}]}]}
    if prefilled:
        tool_input["answers"] = {question: "Duyệt"}
    payload = {"hook_event_name": kind, "tool_name": "AskUserQuestion", "tool_input": tool_input,
               "session_id": "s1", "cwd": "C:/x"}
    if answer is not None:
        payload["tool_response"] = {"answers": {question: answer}}
    return payload


class PauseTest(unittest.TestCase):
    def setUp(self):
        self.root = copy_tree(self, BROKEN)

    def test_a_broken_harness_blocks_every_call_but_asking_the_user(self):
        self.assertEqual(hook(self.root, write_call())[0], 2)
        self.assertEqual(hook(self.root, form(Q, "PreToolUse"))[0], 0)

    def test_the_model_never_answers_the_form_itself(self):
        code, _, err = hook(self.root, form(Q, "PreToolUse", prefilled=True))
        self.assertEqual(code, 2)
        self.assertIn("Only the user answers a form", err)
        self.assertFalse((self.root / "state" / "pause.json").exists())

    def test_duyet_pauses_the_guards_with_a_trace(self):
        code, out, _ = hook(self.root, form(Q, answer="Duyệt"))
        self.assertEqual(code, 0)
        self.assertIn("paused", json.loads(out)["hookSpecificOutput"]["additionalContext"])
        pause = json.loads((self.root / "state" / "pause.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(pause["until"], time.time() + 15 * 60, delta=60)
        self.assertEqual(hook(self.root, write_call())[0], 0)
        trace = (self.root / "state" / "pause.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["what"] for line in trace], ["paused", "passed"])

    def test_another_answer_pauses_nothing(self):
        hook(self.root, form(Q, answer="Không"))
        self.assertEqual(hook(self.root, write_call())[0], 2)

    def test_a_pause_ends_by_itself(self):
        (self.root / "state").mkdir()
        (self.root / "state" / "pause.json").write_text(json.dumps({"until": time.time() - 1, "why": "x"}))
        self.assertEqual(hook(self.root, write_call())[0], 2)

    def test_a_pause_lasts_at_most_two_hours(self):
        hook(self.root, form("Tắt guard 999 phút: x?", answer="Duyệt"))
        pause = json.loads((self.root / "state" / "pause.json").read_text(encoding="utf-8"))
        self.assertLessEqual(pause["until"], time.time() + 120 * 60 + 5)

    def test_a_working_harness_refuses_a_prefilled_form_too(self):
        root = copy_tree(self)
        self.assertEqual(hook(root, form(Q, "PreToolUse", prefilled=True))[0], 2)


class PauseBlockTest(unittest.TestCase):
    def test_the_harness_block_gives_the_question_to_ask(self):
        table = action_table(items_of(CLAUDE_DIR), tree(self, {}))
        out = table.action("harness", "pause").handler(minutes=15, why="sửa harness")
        self.assertIn(Q, out)
        for minutes in (0, 121):
            with self.subTest(minutes=minutes), self.assertRaises(ValueError):
                table.action("harness", "pause").handler(minutes=minutes, why="x")


if __name__ == "__main__":
    unittest.main()
