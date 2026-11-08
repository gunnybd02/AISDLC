"""layout: a file is only where layout.json allows it, matched folder by folder (* never crosses a /)."""
import fnmatch
import json
from pathlib import Path

from nets import files, read

LAYOUT = Path(__file__).with_name("layout.json")


def match(pattern, rel):
    return match_parts(pattern.split("/"), rel.split("/"))


def match_parts(pattern, parts):
    if not pattern:
        return not parts
    if pattern[0] == "**":
        return any(match_parts(pattern[1:], parts[i:]) for i in range(len(parts) + 1))
    return bool(parts) and fnmatch.fnmatchcase(parts[0], pattern[0]) and match_parts(pattern[1:], parts[1:])


def check(claude_dir, layout=LAYOUT):
    try:
        allow = json.loads(read(layout))["allow"]
        if not isinstance(allow, list) or not all(isinstance(p, str) for p in allow):
            raise ValueError("allow is a list of patterns")
    except (OSError, ValueError, KeyError, TypeError) as e:
        return [f"layout: {Path(layout).name} cannot be read ({e})"]
    return [f"layout: {rel} is not in a place layout.json allows"
            for rel, _ in files(claude_dir) if not any(match(p, rel) for p in allow)]
