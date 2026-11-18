"""The form checks of single plan items (docs 04, section 2), and the text helpers the desk cleans items with. Each
check takes the item's raw value (whatever the model sent) and the declared units, and names every problem of its form
as a short phrase; desk.check puts the item's key in front. The checks that need the desk's own patterns (behaviours,
network, children) and the table CHECKS of every item stay in desk.py."""
from __future__ import annotations

import re
from collections.abc import Collection
from typing import Any

OVERVIEW = ("problem", "need", "how", "accept")
STANDALONE = ("none", "agent-code")
MAX_POINTS, MAX_POINT, MAX_CODE, MAX_OVERVIEW = 10, 200, 600, 5
BEHAVIOR_ID = re.compile(r"^[a-z][a-z0-9]*([.-][a-z0-9]+)*$")
BRANCH_RE = re.compile(r"^(?!-)(?!.*\.\.)[A-Za-z0-9._/-]+$")
COMMAND_RE = re.compile(r"^twg\s[^;&|<>`]*$")
CODE_TITLE = re.compile(r"^(pd-\S+|[0-9a-f]{7,})$", re.I)
ABSOLUTE = re.compile(r"^([A-Za-z]:|[\\/~])")
REPO_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
REPO_URL = re.compile(r"^https://[A-Za-z0-9.-]+(:\d+)?/[\w.-]+/[\w.-]+/?$")
REPO_KEYS = ("url", "base", "verify", "path", "pipeline")
PIPELINE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
MAX_REPOS = 10
LIMITS = {"children": 3, "rounds": 3}  # the defaults (spec 05); a plan may lower a limit, never raise it


def one_line(text: Any) -> str:
    """A text on one line: every run of spaces and newlines made one space, none at the ends.

    Args:
        text: the text (any value is made a string first).

    Returns:
        The text on one line.
    """
    return " ".join(str(text).split())


def strings(value: Any) -> list[str]:
    """A list of stripped non-empty strings (one string is a list of one), deduped in order.

    Args:
        value: a string, a list (its non-string entries are left out) or anything else (no entry).

    Returns:
        The strings, stripped, with backslashes made forward slashes, each once.
    """
    items = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return list(dict.fromkeys(s.strip().replace("\\", "/") for s in items if isinstance(s, str) and s.strip()))


def title_problems(title: Any) -> list[str]:
    """The problems of a plan's title: one line of 3 to 80 characters, two words at least, no code, no double quote.

    Args:
        title: the title as given.

    Returns:
        At most one problem; [] when the title is good.
    """
    if not isinstance(title, str) or not title.strip():
        return ["title is needed: one line, 3 to 80 characters, two words at least"]
    t = one_line(title)
    if not 3 <= len(t) <= 80 or len(t.split()) < 2:
        return ["title is one line of 3 to 80 characters, two words at least"]
    if CODE_TITLE.match(t) or '"' in t:
        return ["title is words, not a code, and holds no double quote (the form question quotes it)"]
    return []


def points(value: Any, units: Collection[str] = (), most: int = MAX_POINTS) -> list[str]:
    """The problems of a list of points (what, checks, assumptions, notDoing, risks, teamSkills, a step's points).

    Args:
        value: the item as given.
        units: the declared units (not read).
        most: the most points allowed.

    Returns:
        At most one problem: not a list of strings, too many points, or a point too long.
    """
    if not isinstance(value, list) or not all(isinstance(p, str) and p.strip() for p in value):
        return ["a list of points (strings)"]
    if len(value) > most:
        return [f"at most {most} points"]
    return [f"a point of more than {MAX_POINT} characters" for p in value if len(p) > MAX_POINT][:1]


def path_problems(value: Any, units: Collection[str] = (), required: bool = False) -> list[str]:
    """The problems of a list of paths: each relative to the root, not in .git, a folder with / or a file with an
    extension, with no space, % or comma.

    Args:
        value: the item as given.
        units: the declared units (not read).
        required: True when the list may not be empty.

    Returns:
        One problem per bad path, or one for a value that is not a list of strings (or empty when required).
    """
    if not isinstance(value, list) or not all(isinstance(p, str) and p.strip() for p in value):
        return ["a list of paths"]
    if required and not value:
        return ["at least one path"]
    out = []
    for p in value:
        parts = [s.lower() for s in re.split(r"[\\/]", p)]
        if ABSOLUTE.match(p) or ".." in parts:
            out.append(f"{p} is not a path inside the root (relative, no ..)")
        elif ".git" in parts:
            out.append(f"{p} is inside .git, which no plan edits")
        elif any(mark in p for mark in "%, ") or ("/" not in p and "." not in p):
            out.append(f"{p} is not a path: a folder with / or a file with an extension, no space, % or comma")
    return out


def overview_problems(value: Any, units: Collection[str] = ()) -> list[str]:
    """The problems of an overview: exactly problem, need, how and accept, each 1 to MAX_OVERVIEW short points.

    Args:
        value: the item as given.
        units: the declared units (not read).

    Returns:
        One problem per bad key, or one for a value of other keys.
    """
    if not isinstance(value, dict) or set(value) != set(OVERVIEW):
        return [f"an object of {', '.join(OVERVIEW)}"]
    out = []
    for k in OVERVIEW:
        pts = strings(value[k])
        if not pts:
            out.append(f"{k} is needed")
        elif len(pts) > MAX_OVERVIEW or any(len(x) > MAX_POINT for x in pts):
            out.append(f"{k} is at most {MAX_OVERVIEW} points of at most {MAX_POINT} characters")
    return out


def code_problems(value: Any, units: Collection[str] = ()) -> list[str]:
    """The problems of the code item: a list of {file, code, reason}, a good path and two short texts each.

    Args:
        value: the item as given.
        units: the declared units (not read).

    Returns:
        The problems of every entry; [] when all are good.
    """
    if not isinstance(value, list):
        return ["a list of {file, code, reason}"]
    out = []
    for c in value:
        if not isinstance(c, dict) or set(c) != {"file", "code", "reason"}:
            out.append("each is {file, code, reason}")
            continue
        out += path_problems([c["file"]]) if isinstance(c["file"], str) else ["file is a path"]
        out += [f"{k} is text of at most {MAX_CODE} characters" for k in ("code", "reason")
                if not isinstance(c[k], str) or not c[k].strip() or len(c[k]) > MAX_CODE]
    return out


def test_problems(value: Any, units: Collection[str] = ()) -> list[str]:
    """The problems of the test item: a list of {file, name, expects, how, why, step?}, name a behaviour id.

    Args:
        value: the item as given.
        units: the declared units (not read).

    Returns:
        The problems of every entry; [] when all are good.
    """
    if not isinstance(value, list):
        return ["a list of {file, name, expects, how, why, step?}"]
    out = []
    for t in value:
        if not isinstance(t, dict) or not {"file", "name", "expects", "how", "why"} <= set(t) or set(t) - {
                "file", "name", "expects", "how", "why", "step"}:
            out.append("each is {file, name, expects, how, why, step?}")
            continue
        out += path_problems([t["file"]]) if isinstance(t["file"], str) else ["file is a path"]
        if not isinstance(t["name"], str) or not BEHAVIOR_ID.match(t["name"]):
            out.append(f"name {t['name']!r} is a behaviour id (a.b-c)")
        if not isinstance(t["why"], str) or len(t["why"]) > MAX_POINT:
            out.append(f"why is at most {MAX_POINT} characters")
    return out


def services_problems(value: Any, units: Collection[str] = ()) -> list[str]:
    """The problems of services: the plan's own repos or declared units, or none or agent-code alone.

    Args:
        value: the item as given.
        units: the declared units.

    Returns:
        One problem for a bad list, else one per service that is no declared unit.
    """
    if not isinstance(value, list) or not value:
        return ["a list of units, or none, or agent-code"]
    if any(s in STANDALONE for s in value) and len(value) > 1:
        return ["none and agent-code stand alone"]
    return [f"{s} is no declared unit and no repo of the plan" for s in value if s not in STANDALONE and s not in units]


def repo_key(url: str) -> str:
    """The owner/name of a repository URL or remote, lower case, with ".git" and a trailing slash left out: how two
    names of one repository compare (an https URL, an ssh remote, a proxy remote).

    Args:
        url: a repository URL or a git remote.

    Returns:
        "owner/name", or "" when the URL has fewer than two path parts.
    """
    parts = [p for p in str(url or "").strip().replace("\\", "/").replace(":", "/").split("/") if p]
    if len(parts) < 3:
        return ""
    name = parts[-1][:-4] if parts[-1].endswith(".git") else parts[-1]
    return f"{parts[-2]}/{name}".lower()


def repo_problems(name: Any, spec: Any) -> list[str]:
    """The problems of one entry of repos: its name, and {url, base?, verify?, path?, pipeline?}.

    Args:
        name: the repository's name in the plan.
        spec: what the plan says of it.

    Returns:
        Each problem, starting with the name.
    """
    if not isinstance(name, str) or not REPO_NAME.match(name) or name in STANDALONE or name == "home":
        return [f"{name!r} is no repository name (a-z, 0-9, -; not home, none or agent-code)"]
    if not isinstance(spec, dict) or set(spec) - set(REPO_KEYS):
        return [f"{name}: {{{', '.join(REPO_KEYS)}}} only"]
    out = []
    if not isinstance(spec.get("url"), str) or not REPO_URL.match(spec["url"]):
        out.append(f"{name}: url is the https URL of a repository (https://host/owner/name)")
    base = spec.get("base", "main")
    if not isinstance(base, str) or not BRANCH_RE.match(base):
        out.append(f"{name}: base is a branch name")
    verify = spec.get("verify", ["x"])
    if not isinstance(verify, list) or not verify or not all(isinstance(w, str) and w.strip() for w in verify):
        out.append(f"{name}: verify is the test command, a list of words")
    path = spec.get("path", ".")
    if not isinstance(path, str) or ABSOLUTE.match(path) or ".." in path.replace("\\", "/").split("/"):
        out.append(f"{name}: path is a folder inside the repository")
    if "pipeline" in spec and not (isinstance(spec["pipeline"], str) and PIPELINE_NAME.match(spec["pipeline"])):
        out.append(f"{name}: pipeline is the name of a pipeline file")
    return out


def repos_problems(value: Any, units: Collection[str] = ()) -> list[str]:
    """The problems of repos: the repositories the plan works on, by name, each {url, base?, verify?, path?,
    pipeline?}; form 1 shows them, so nothing is declared in advance.

    Args:
        value: the item as given.
        units: the declared units (not read).

    Returns:
        One problem for a bad map, else every problem of every entry.
    """
    if not isinstance(value, dict) or not value or len(value) > MAX_REPOS:
        return [f"a map of 1 to {MAX_REPOS} repositories by name, each {{url, base?, verify?, path?, pipeline?}}"]
    return [p for name, spec in value.items() for p in repo_problems(name, spec)]


def limits_problems(value: Any, units: Collection[str] = ()) -> list[str]:
    """The problems of limits: children and rounds, each a whole number from 1 to its default (a plan may lower a
    limit, never raise it).

    Args:
        value: the item as given.
        units: the declared units (not read).

    Returns:
        One problem for a bad map, else one per limit out of range.
    """
    if not isinstance(value, dict) or not value or set(value) - set(LIMITS):
        return [f"a map of {', '.join(LIMITS)} to whole numbers"]
    return [f"{k} is a whole number from 1 to {LIMITS[k]}: a plan may lower a limit, never raise it"
            for k, v in value.items() if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= LIMITS[k]]


def run_limits(items: Any, base: dict[str, int]) -> dict[str, int]:
    """The limits a plan runs with: each of base, lowered by the plan's own limits item when it gives a lower one.

    Args:
        items: the plan's items (any value: no limits item means none).
        base: the limits that hold without the plan, {children, rounds}.

    Returns:
        {name: number} for each limit of base.
    """
    own = items.get("limits") if isinstance(items, dict) and isinstance(items.get("limits"), dict) else {}
    return {k: min(int(v), int(own[k])) if isinstance(own.get(k), int) and not isinstance(own[k], bool) else int(v)
            for k, v in base.items()}


def steps_problems(value: Any, units: Collection[str] = ()) -> list[str]:
    """The problems of steps: a list of {commit, points, files, tests?, behaviors?}, with a message, points and paths.

    Args:
        value: the item as given.
        units: the declared units (not read).

    Returns:
        The problems of every step, each starting "step <n>"; [] when all are good.
    """
    if not isinstance(value, list) or not value:
        return ["a list of {commit, points, files, tests, behaviors?}"]
    out = []
    for n, s in enumerate(value, 1):
        if not isinstance(s, dict) or not {"commit", "points", "files"} <= set(s) or set(s) - {
                "commit", "points", "files", "tests", "behaviors"}:
            out.append(f"step {n} is {{commit, points, files, tests, behaviors?}}")
            continue
        if not isinstance(s["commit"], str) or not s["commit"].strip():
            out.append(f"step {n}: commit is its message")
        out += [f"step {n}: {p}" for p in points(s["points"]) + path_problems(s["files"], required=True)
                + path_problems(s.get("tests", []))]
    return out


def commands_problems(value: Any, units: Collection[str] = ()) -> list[str]:
    """The problems of commands: at most 30 twg lines of at most 400 characters, no ; & | < > or backtick.

    Args:
        value: the item as cleaned (a list of one-line strings).
        units: the declared units (not read).

    Returns:
        One problem for too many lines, else one per bad line.
    """
    if len(value) > 30:
        return ["at most 30 lines"]
    return [f"{c!r} is one twg line of at most 400 characters, no ; & | < > or backtick"
            for c in value if len(c) > 400 or not COMMAND_RE.match(c)]


def branch_problems(value: Any, units: Collection[str] = ()) -> list[str]:
    """The problems of a branch name.

    Args:
        value: the item as given.
        units: the declared units (not read).

    Returns:
        [] for a good branch name, else one problem.
    """
    return [] if isinstance(value, str) and BRANCH_RE.match(value) else [f"{value!r} is not a branch name"]
