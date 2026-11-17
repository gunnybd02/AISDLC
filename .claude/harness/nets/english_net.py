"""english: the text of the harness is English (spec 13 section 9). A letter or a combining mark above code point 127
in a .py .json .md .yaml .yml .sql or .txt file is reported; symbols, punctuation, emoji and written escapes are free,
and so are the tests (they may hold any text they feed the harness). project/behaviors.json is not read (nets/__init__)."""
from __future__ import annotations

import unicodedata
from pathlib import Path

from harness.nets import files, read

SUFFIXES = (".py", ".json", ".md", ".yaml", ".yml", ".sql", ".txt")
TESTS = "harness/tests/"


def foreign(line: str) -> str:
    """The first letter or combining mark of a line above code point 127.

    Args:
        line: one line of text.

    Returns:
        The character, or "" when there is none.
    """
    return next((c for c in line if ord(c) > 127 and unicodedata.category(c)[0] in "LM"), "")


def check(claude_dir: Path) -> list[str]:
    """Every line of a text file outside the tests that holds a letter outside ASCII.

    Args:
        claude_dir: the .claude folder read.

    Returns:
        "english: <file>: line <n> holds a letter outside ASCII (U+XXXX); write English, or an escape" lines.
    """
    out = []
    for rel, path in files(claude_dir, SUFFIXES):
        if rel.startswith(TESTS):
            continue
        try:
            text = read(path)
        except UnicodeDecodeError:
            continue  # size_net reports it
        for n, line in enumerate(text.splitlines(), 1):
            c = foreign(line)
            if c:
                out.append(f"english: {rel}: line {n} holds a letter outside ASCII (U+{ord(c):04X}); write English, "
                           "or an escape")
    return out
