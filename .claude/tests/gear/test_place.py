"""h8.edit-gate: a file is edited only under an approved plan and only if the plan names it; the harness's own state is
never edited; the model never fills in the answers of a form."""
import ctypes
import json
import unittest

import harness.gear as gear_block
from harness.assemble.engine.build import build_runner
from harness.assemble.engine.ports import LedgerPort, question
from harness.gear.decide.arbiter import Decide
from harness.gear.detect.forms import Forms
from harness.gear.detect.planfiles import PlanFiles
from harness.gear.detect.tracked import Tracked
from harness.hooks.forms import Answers
from harness.gear.translate.place import Places
from harness.utils.contracts import Event, Finding
from tests import CLAUDE_DIR, tree
from tests.e2e import copy_tree

ROOT = "C:/repo"
PLAN = {"id": 1, "plan_id": "pd-1", "rev": 1, "root": ROOT, "title": "t", "files": ["src/a.py"], "tests": ["test_a.py"]}
STATE = "C:/harness/.claude/state"


def gate(event, facts):
    """The findings of the three detectors of the edit gate, in the order the recipe runs them."""
    return [f for d in (Forms(), Tracked(), PlanFiles()) for f in d.detect(event, facts)]


def write(path, tool="Write", cwd=ROOT):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return Event("PreToolUse", tool, {key: path}, "s1", cwd)


def kinds(event, plan=PLAN, state=STATE):
    facts = {**Places().translate(event), "plan": plan, "state_dir": state}
    return [f.kind for f in gate(event, facts)]


class PlacesTest(unittest.TestCase):
    def test_the_editing_tools_give_absolute_paths(self):
        for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            with self.subTest(tool=tool):
                self.assertEqual(Places().translate(write("src/a.py", tool))["writes"], ["C:/repo/src/a.py"])
        self.assertNotIn("writes", Places().translate(Event("PreToolUse", "Read", {"file_path": "x"})))  # a read names, never writes


SAID = "Delete the build folder of the project"


def shell(command, tool="Bash", said=SAID, cwd=ROOT, kind="PreToolUse"):
    return Event(kind, tool, {"command": command, "description": said}, "s1", cwd)


def shell_facts(command, **kw):
    return Places().translate(shell(command, **kw))


if __name__ == "__main__":
    unittest.main()
