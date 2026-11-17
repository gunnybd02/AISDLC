"""Tests of the harness. CLAUDE_DIR is the real .claude folder; tree() writes a fake one for a test."""
import os
import re
import shutil
import tempfile
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parent.parent.parent
os.environ.pop("HARNESS_DRIVE_FOLDER", None)  # the tests never see the user's store: one that needs a folder sets its own
for _name in ("HARNESS_HOME", "HARNESS_CODE", "HARNESS_SESSION", "CLAUDE_PROJECT_DIR"):
    os.environ.pop(_name, None)  # run in a governed shell, the tests never reach the live home, its release or session
WINDOWS = os.name == "nt"


def native(text):
    """A test's Windows path (C:/x, C:\\x) as this system writes the same place: as is on Windows, /x elsewhere."""
    return text if WINDOWS else re.sub(r"[Cc]:(?=[\\/])", "", text)


def tree(test, files):
    """Write {relative path: text} under a new temp folder, removed when the test ends; return the folder."""
    root = Path(tempfile.mkdtemp(prefix="harness-test-"))
    test.addCleanup(shutil.rmtree, root, True)
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def entry_of(home, name):
    """An entry script of a .claude folder: harness/entry/<name>.py."""
    return Path(home) / "harness" / "entry" / f"{name}.py"


def anchor_of(home):
    """The anchor of a .claude folder: anchor.py beside it."""
    return Path(home).parent / "anchor.py"


_JUDGE = []  # the judge of the real rules, loaded once


def plan_paths(event, facts):
    """The findings of the real when rows for the plan-files check: PlanPaths, then the matcher."""
    from harness.gear.decide.arbiter import Decide
    from harness.gear.translate.planfiles import PlanPaths
    if not _JUDGE:
        _JUDGE.append(Decide.load(CLAUDE_DIR))
    return _JUDGE[0].matched(PlanPaths().translate(event, facts).get("rule_actions", []))


def edit_gate(event, facts):
    """The findings of the edit gate in the order the floor runs them: Forms, Tracked, then the plan-files rows."""
    from harness.gear.detect.forms import Forms
    from harness.gear.detect.tracked import Tracked
    return [f for d in (Forms(), Tracked()) for f in d.detect(event, facts)] + plan_paths(event, facts)
