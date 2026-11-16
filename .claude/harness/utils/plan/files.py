"""The files a plan names, and paths as the gates compare them: real paths (8.3 short names expanded), no \\\\?\\
prefix, case folded where the system folds it."""
from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Optional

from harness.utils.shapes import ApprovedPlan, PlanItems

PREFIXES = ("\\\\?\\", "//?/", "\\\\.\\", "//./")


def resolved(path: str | Path) -> str:
    """A path as the system resolves it: a \\\\?\\ (or //?/, \\\\.\\, //./) prefix taken off, then the real path.

    Args:
        path: a path, absolute or from the working folder.

    Returns:
        The real absolute path (links followed, 8.3 short names expanded).
    """
    path = str(path)
    for prefix in PREFIXES:
        if path.startswith(prefix):
            path = path[len(prefix):]
    return os.path.realpath(path)


def key(path: str | Path) -> str:
    """A path as the gates compare it: resolved, and case folded where the system folds it.

    Args:
        path: a path, absolute or from the working folder.

    Returns:
        The comparison key.
    """
    return os.path.normcase(resolved(path))


def rel_key(path: str) -> str:
    """A path from a plan's root as the gates compare it.

    Args:
        path: a path from a plan's root.

    Returns:
        The path normalised (no ./, no a/../) and case folded where the system folds it.
    """
    return os.path.normcase(os.path.normpath(path))


def named(plan: PlanItems) -> set[str]:
    """The files and tests a plan names, as the gates compare them.

    Args:
        plan: a plan's items; files and tests are read.

    Returns:
        The rel_key of each entry (patterns as written).
    """
    return {rel_key(p) for p in plan["files"] + plan.get("tests", [])}


def relative(path: str | Path, root: str | Path) -> Optional[str]:
    """path from root, or None when path is not under root.

    Args:
        path: a path, absolute or from the working folder.
        root: the folder (a plan's root).

    Returns:
        The path from root in the system's own form ("." for root itself), or None outside it or on another drive.
    """
    try:
        rel = os.path.relpath(key(path), key(root))
    except ValueError:  # another drive
        return None
    return None if rel == os.pardir or rel.startswith(os.pardir + os.sep) else rel


WILD = set("*?")


def is_pattern(path: str) -> bool:
    """Whether a plan path is a pattern: it holds * or ?, or ends with / (a folder).

    Args:
        path: a path as a plan names it.

    Returns:
        True for a pattern.
    """
    return bool(WILD & set(path)) or path.endswith("/")


def pattern_re(pattern: str) -> re.Pattern[str]:
    """A plan path as a regex of paths from the root: ** any run (/ too), * no /, ? one character, a trailing / a
    folder and everything below it.

    Args:
        pattern: a plan path (a pattern or a plain path).

    Returns:
        The compiled regex of whole paths with forward slashes; case ignored where the system folds case.
    """
    p = pattern.replace("\\", "/").strip("/") if pattern.endswith("/") else pattern.replace("\\", "/")
    out, i = "", 0
    while i < len(p):
        if p.startswith("**", i):
            out += ".*"
            i += 2
            if p.startswith("/", i):
                out += "(?:/)?"
                i += 1
        elif p[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif p[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(p[i]), i + 1
    return re.compile(f"^{out}(/.*)?$" if pattern.endswith("/") else f"^{out}$",
                      re.I if os.path.normcase("A") == "a" else 0)


def matches(patterns: Iterable[str], rel: str) -> bool:
    """Whether a path from the root matches one of the plan paths.

    Args:
        patterns: plan paths (patterns or plain paths).
        rel: a path from the plan's root.

    Returns:
        True when one matches.
    """
    rel = rel_key(rel).replace("\\", "/")
    return any(pattern_re(rel_key(p).replace("\\", "/") if not is_pattern(p) else p).match(rel) for p in patterns)


def allows(plan: ApprovedPlan, rel: str) -> bool:
    """Whether the plan allows the path rel (from its root): the newest grant of that path decides (add allows, drop
    refuses), else a pattern of its files and tests matches.

    Args:
        plan: the approved plan; grants, files and tests are read.
        rel: a path from the plan's root.

    Returns:
        True when the plan allows writing it.
    """
    for op, path in reversed(plan.get("grants", [])):
        if rel_key(path) == rel_key(rel):
            return op == "add"
    return matches(plan.get("files", []) + plan.get("tests", []), rel)


def holds(plan: PlanItems, rel: str) -> bool:
    """Whether rel is a folder above a planned file (a mkdir of it is no write of a file): above a named file, above the
    fixed part of a pattern, or under a ** of one.

    Args:
        plan: a plan's items; files and tests are read.
        rel: a folder from the plan's root.

    Returns:
        True when a planned file may lie below it.
    """
    folder = rel_key(rel).replace("\\", "/").rstrip("/")
    for p in plan.get("files", []) + plan.get("tests", []):
        p = p.replace("\\", "/")
        if not is_pattern(p):
            if rel_key(p).replace("\\", "/").startswith(folder + "/"):
                return True
            continue
        head = re.split(r"[*?]", p, 1)[0]  # the fixed part: src/ of src/**/*.py, docs/ of docs/
        base = head.rsplit("/", 1)[0] if "/" in head else ""
        if (base + "/").startswith(folder + "/") or ("**" in p and folder.startswith(base + "/")):
            return True
    return False
