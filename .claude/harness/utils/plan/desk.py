"""The desk of a plan (docs 04, section 2): a plan is data. clean keeps the known items in their shape, normalize fills
what follows from them (behaviours from steps and tests, files and tests from steps and code, services of a light
plan), check names every problem, merge applies a revision. A plan with problems is not kept.

tier: full when any of steps, behaviors, code, test, children is given, else light. A light plan needs a title (when
new), what (or overview.need) and files; a full plan needs services, what, files, checks, assumptions, notDoing and
risks, and on a new plan an overview and code too.

Paths are relative to the plan's root (the folder the MCP server runs in), inside it, never in .git. The form checks of
single items are in item_checks.py; CHECKS here names the check of every item."""
from __future__ import annotations

import re
import secrets
import time
from collections.abc import Collection, Iterable
from typing import Any, Optional

from harness.utils.orchestra import card
from harness.utils.plan.item_checks import (BEHAVIOR_ID, MAX_POINT, STANDALONE, branch_problems, code_problems,
                                            banned_problems, commands_problems, limits_problems, one_line,
                                            overview_problems,
                                            path_problems, points, repos_problems, services_problems, steps_problems,
                                            strings, test_problems, title_problems)
from harness.utils.plan.tickets import base36
from harness.utils.shapes import PlanItems

KEYS = ("title", "overview", "code", "test", "repos", "limits", "banned", "services", "branch", "what", "files", "tests",
        "checks", "commit", "steps", "behaviors", "network", "commands", "children", "teamSkills", "assumptions",
        "notDoing", "risks")
POINTS = ("what", "checks", "assumptions", "notDoing", "risks")
RECORD = ("title", "overview", "code", "checks", "assumptions", "notDoing", "risks")
FULL_MARKS = ("steps", "behaviors", "code", "test", "children")
FULL_REQUIRED = ("services", "what", "files", "checks", "assumptions", "notDoing", "risks")
STEP_ID = re.compile(r"^s(\d+)\.")
HOST_RE = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*$")


def new_id() -> str:
    """A new desk id.

    Returns:
        "pd-<the time in ms, base 36>-<6 random hex characters>".
    """
    return f"pd-{base36(int(time.time() * 1000))}-{secrets.token_hex(3)}"


def clean(raw: dict[str, Any]) -> PlanItems:
    """The known items of raw in their plain shape; optional items only when given.

    Args:
        raw: the plan as the model sent it (unknown keys are left out here; unknown() names them).

    Returns:
        The items of KEYS that raw holds: title and branch on one line, commit without markdown marks, lists of points
        and paths as clean strings; other items as given.
    """
    out = {}
    for key in KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if key in ("title", "branch") and isinstance(value, str):
            value = one_line(value)
        elif key == "commit" and isinstance(value, str):
            value = one_line(re.sub(r"[`*_|]", "", value))
        elif key in POINTS or key in ("services", "files", "tests", "teamSkills", "commands", "banned"):
            value = strings(value) if key != "commands" else [one_line(c) for c in strings(value)]
        out[key] = value
    return out


def normalize(items: PlanItems) -> PlanItems:
    """What follows from the items: step and test behaviours, files and tests of steps and code, light services.

    Args:
        items: cleaned items (clean, or a merge of them).

    Returns:
        A new dict: children cleaned (utils/orchestra/card.clean_cards), behaviors gains the steps' (ids "s<n>.<id>")
        and the test item's, files and tests gain those of the steps, code and test, and a light plan with no services
        gets ["agent-code"].
    """
    out = dict(items)
    if "children" in items:
        out["children"] = card.clean_cards(items["children"])
    behaviors = [dict(b) for b in items.get("behaviors", []) if isinstance(b, dict)]
    for n, step in enumerate(s for s in items.get("steps", []) if isinstance(s, dict)):
        for b in step.get("behaviors", []) if isinstance(step.get("behaviors"), list) else []:
            if isinstance(b, dict) and isinstance(b.get("id"), str):
                bid = b["id"] if STEP_ID.match(b["id"]) else f"s{n + 1}.{b['id']}"
                behaviors.append({**b, "id": bid, "step": n + 1})
    accept = "; ".join(strings((items.get("overview") or {}).get("accept", []))) if isinstance(
        items.get("overview"), dict) else ""
    for t in items.get("test", []) if isinstance(items.get("test"), list) else []:
        if isinstance(t, dict) and isinstance(t.get("name"), str):
            b = {"id": t["name"], "what": t.get("expects", ""), "how": t.get("how", ""),
                 "why": t.get("why") or accept, "test": t.get("file", "")}
            behaviors.append({**b, "step": t["step"]} if "step" in t else b)
    if behaviors:
        out["behaviors"] = list({b.get("id"): b for b in behaviors}.values())
    steps = [s for s in items.get("steps", []) if isinstance(s, dict)]
    code = [c.get("file") for c in items.get("code", []) if isinstance(c, dict)] if isinstance(items.get("code"), list) else []
    tests = [t.get("file") for t in items.get("test", []) if isinstance(t, dict)] if isinstance(items.get("test"), list) else []
    files = strings(items.get("files", []) + [f for s in steps for f in strings(s.get("files", []))] + strings(code))
    out["files"] = files
    if items.get("tests") or steps or tests:
        out["tests"] = strings(items.get("tests", []) + [f for s in steps for f in strings(s.get("tests", []))]
                               + strings(tests))
    if tier(out) == "light" and not out.get("services"):
        out["services"] = ["agent-code"]
    return out


def merge(old: PlanItems, changes: PlanItems) -> PlanItems:
    """A revision: each given item replaces the old one whole; without steps, new files and tests join the last step.
    A replaced test or steps item takes the behaviours it made with it (normalize keeps them in behaviors).

    Args:
        old: the items of the newest revision (without root).
        changes: the cleaned items of the revision.

    Returns:
        The new items, not normalized.
    """
    out = {**old, **changes}
    if "behaviors" not in changes and ("test" in changes or "steps" in changes):  # those the old item made go with it
        gone = {t.get("name") for t in old.get("test", []) if isinstance(t, dict)} if "test" in changes else set()
        for n, step in enumerate(old.get("steps", []) if "steps" in changes else []):
            for b in step.get("behaviors", []) if isinstance(step, dict) else []:
                if isinstance(b, dict) and isinstance(b.get("id"), str):
                    gone.add(b["id"] if STEP_ID.match(b["id"]) else f"s{n + 1}.{b['id']}")
        out["behaviors"] = [b for b in old.get("behaviors", []) if not (isinstance(b, dict) and b.get("id") in gone)]
    if "steps" not in changes and old.get("steps"):
        steps = [dict(s) for s in old["steps"]]
        last = steps[-1]
        for key in ("files", "tests"):
            new = [p for p in strings(changes.get(key, [])) if p not in strings(old.get(key, []))]
            if new:
                last[key] = strings(last.get(key, []) + new)
        out["steps"] = steps
    return out


def tier(items: PlanItems) -> str:
    """The tier of a plan.

    Args:
        items: the plan's items.

    Returns:
        "full" when any of steps, behaviors, code, test, children is given, else "light".
    """
    return "full" if any(items.get(k) for k in FULL_MARKS) else "light"


def unknown(raw: dict[str, Any]) -> list[str]:
    """The keys of a raw plan that are no item.

    Args:
        raw: the plan as the model sent it.

    Returns:
        "unknown item <key>" for each key not in KEYS.
    """
    return [f"unknown item {k}" for k in raw if k not in KEYS]


def check(items: PlanItems, need_title: bool = True, keys: Optional[Iterable[str]] = None,
          units: Collection[str] = ()) -> list[str]:
    """Every problem of the items: the form of each item (only those in keys, when given), then what the tier needs.

    Args:
        items: normalized items.
        need_title: True for a new plan: the title is checked and a full plan needs overview and code.
        keys: the items whose form is checked (a revision's changed items); None for all.
        units: the declared units, for services and children; the plan's own repos join them.

    Returns:
        Every problem, "<key>: <problem>" for an item's form; [] when the plan may be kept.
    """
    look = set(items) if keys is None else set(keys)
    units = set(units) | (set(items["repos"]) if isinstance(items.get("repos"), dict) else set())
    out = []
    if need_title or "title" in look:
        out += title_problems(items.get("title"))
    for key in sorted(look - {"title"}):
        if key in items:
            out += [f"{key}: {p}" for p in CHECKS.get(key, lambda v, u: [])(items[key], units)]
    full = tier(items) == "full"
    for key in FULL_REQUIRED if full else ("files",):
        if not items.get(key):
            out.append(f"{key} is needed on a {'full' if full else 'light'} plan")
    if not full and not items.get("what") and not (isinstance(items.get("overview"), dict)
                                                  and items["overview"].get("need")):
        out.append("what (or overview.need) is needed on a light plan")
    if full and need_title:
        out += [f"{k} is needed on a new full plan" for k in ("overview", "code") if not items.get(k)]
    return out


def behaviors_problems(value: Any, units: Collection[str] = ()) -> list[str]:
    """The problems of behaviors: each {id, what, how, why, test?}, its id a behaviour id whose s<n>. matches its step.

    Args:
        value: the item as given.
        units: the declared units (not read).

    Returns:
        The problems of every behaviour; [] when all are good.
    """
    if not isinstance(value, list):
        return ["a list of {id, what, how, why, test?}"]
    out = []
    for b in value:
        if not isinstance(b, dict) or not isinstance(b.get("id"), str) or not BEHAVIOR_ID.match(b["id"]):
            out.append("each has an id like a.b-c")
            continue
        out += [f"{b['id']}: {k} is needed" for k in ("what", "how", "why") if not str(b.get(k) or "").strip()]
        m = STEP_ID.match(b["id"])
        if m and "step" in b and b["step"] != int(m.group(1)):
            out.append(f"{b['id']}: its step is {m.group(1)}, not {b['step']}")
    return out


def network_problems(value: Any, units: Collection[str] = ()) -> list[str]:
    """The problems of network: at most 20 {host, port, why}, a bare host name and a port 1-65535 each.

    Args:
        value: the item as given.
        units: the declared units (not read).

    Returns:
        One problem for a bad list, else one per bad entry.
    """
    if not isinstance(value, list) or len(value) > 20:
        return ["a list of at most 20 {host, port, why}"]
    return [f"{n.get('host') if isinstance(n, dict) else n!r}: a host name (no scheme, path or port), a port 1-65535 "
            "and why" for n in value if not (isinstance(n, dict) and isinstance(n.get("host"), str)
                                             and HOST_RE.match(n["host"]) and isinstance(n.get("port"), int)
                                             and 1 <= n["port"] <= 65535 and str(n.get("why") or "").strip())]


CHECKS = {**{k: points for k in POINTS}, "overview": overview_problems, "code": code_problems,
          "test": test_problems, "repos": repos_problems, "limits": limits_problems, "banned": banned_problems,
          "services": services_problems, "steps": steps_problems,
          "behaviors": behaviors_problems, "network": network_problems, "commands": commands_problems,
          "children": card.card_problems, "branch": branch_problems, "teamSkills": points,
          "files": lambda v, u: path_problems(v, required=True), "tests": path_problems,
          "commit": lambda v, u: [] if isinstance(v, str) else ["the commit message"]}
