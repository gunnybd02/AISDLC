"""layout: a file is only where layout.json allows it, matched folder by folder (* never crosses a /)."""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path

from harness.nets import files, read

LAYOUT = Path(__file__).with_name("layout.json")


def match(pattern: str, rel: str) -> bool:
    """Whether a path matches a pattern of layout.json.

    Args:
        pattern: the pattern (* inside one folder name, ** any number of folders).
        rel: the file's posix path from the .claude folder.

    Returns:
        True when it matches.
    """
    return match_parts(pattern.split("/"), rel.split("/"))


def match_parts(pattern: list[str], parts: list[str]) -> bool:
    """Whether the folder names of a path match the parts of a pattern, one by one.

    Args:
        pattern: the pattern's parts.
        parts: the path's parts.

    Returns:
        True when they match.
    """
    if not pattern:
        return not parts
    if pattern[0] == "**":
        return any(match_parts(pattern[1:], parts[i:]) for i in range(len(parts) + 1))
    return bool(parts) and fnmatch.fnmatchcase(parts[0], pattern[0]) and match_parts(pattern[1:], parts[1:])


def check(claude_dir: Path, layout: str | Path = LAYOUT) -> list[str]:
    """Every file of the tree that no pattern of layout.json allows, or the one problem that layout.json cannot be read.

    Args:
        claude_dir: the .claude folder read.
        layout: the layout file ({"allow": [patterns]}).

    Returns:
        "layout: <file> is not in a place layout.json allows" lines.
    """
    try:
        allow = json.loads(read(layout))["allow"]
        if not isinstance(allow, list) or not all(isinstance(p, str) for p in allow):
            raise ValueError("allow is a list of patterns")
    except (OSError, ValueError, KeyError, TypeError) as e:
        return [f"layout: {Path(layout).name} cannot be read ({e})"]
    return [f"layout: {rel} is not in a place layout.json allows"
            for rel, _ in files(claude_dir) if not any(match(p, rel) for p in allow)]
