"""h10.pause: only the user's "Duyệt" in the form 'Tắt guard N phút: why?' pauses the guards, for N minutes at most
120, with a trace; it works when the harness itself is broken, and the model can neither answer the form nor ask for
the pause around a broken harness."""
import json
import time
import unittest

from harness.assemble.engine.build import items_of
from harness.assemble.engine.wire_mcp import action_table
from tests import CLAUDE_DIR, tree
from tests.e2e import WINDOWS_CONSOLE, copy_tree, run

BROKEN = {"harness/assemble/engine/build.py": "raise RuntimeError('broken')\n"}
Q = "Tắt guard 15 phút: sửa harness?"


def hook(root, payload):
    return run(root / "entry" / "hook.py", json.dumps(payload), env=WINDOWS_CONSOLE)


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
