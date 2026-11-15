"""Tests of the harness. CLAUDE_DIR is the real .claude folder; tree() writes a fake one for a test."""
import os
import re
import shutil
import tempfile
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parent.parent.parent
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
