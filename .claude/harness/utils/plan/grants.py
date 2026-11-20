"""The CLI doors that widen or shrink an approved plan without a new approval (docs 04, section 4), and the behaviour
registry they keep. Each door judges its own arguments and refuses with why (DoorError); it writes chained rows only:
pl_file_grants (add, drop) and pl_behaviors (add, retire). A wider change (a unit, a host, a step) is plan_revise.

A behaviour of the registry is {what, how, why, tests: [file or file#name], status, step}; rows replay in order: add
merges and unions tests, retire and skip set the status (active, pending, skipped, retired)."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Sequence
from typing import Optional

from harness.utils.plan.item_checks import BEHAVIOR_ID
from harness.utils.plan.files import allows, matches, relative
from harness.utils.shapes import ApprovedPlan, Behaviour, PlanStore

LONGEST_WHY = 200


class DoorError(ValueError):
    """A CLI door refuses its arguments; the message says why."""


def replay(rows: Iterable[tuple[str, str, Optional[str]]]) -> dict[str, Behaviour]:
    """{id: behaviour} from the pl_behaviors rows (op, id, entry), in the order they were written.

    Args:
        rows: (op, behaviour id, entry as JSON or None) of each row; op add, skip or retire (others change nothing).

    Returns:
        {behaviour id: Behaviour}; a new entry starts active with no test.
    """
    out = {}
    for op, bid, entry in rows:
        entry = json.loads(entry or "{}")
        now = out.get(bid, {"tests": [], "status": "active"})
        if op == "add":
            tests = list(dict.fromkeys(now["tests"] + entry.get("tests", [])))
            now = {**now, **{k: v for k, v in entry.items() if k != "tests" and v is not None}, "tests": tests}
        elif op in ("skip", "retire"):
            now = {**now, "status": {"skip": "skipped", "retire": "retired"}[op]}
        out[bid] = now
    return out


def test_missing(root: str, test: str) -> str:
    """Why a test (file or file#name, from the root) is missing, or "": no file, or no test of that name in it.

    Args:
        root: the plan's root.
        test: "file" or "file#name" from the root; a name ending in * is a prefix.

    Returns:
        "<file> does not exist", "<file> has no test <name>", or "" when it is there.
    """
    file, _, name = test.partition("#")
    path = os.path.join(root, file)
    if not os.path.isfile(path):
        return f"{file} does not exist"
    if not name:
        return ""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    prefix = name.endswith("*")
    word = re.escape(name.rstrip("*")) + (r"\w*" if prefix else r"\b")
    found = re.search(rf"def\s+{word}|\b(?:test|it)\(\s*['\"]{re.escape(name.rstrip('*'))}", text)
    return "" if found else f"{file} has no test {name}"


def why_of(why: Optional[str]) -> str:
    """The --why of a door, checked.

    Args:
        why: the reason given.

    Returns:
        The reason without spaces around it.

    Raises:
        DoorError: it is empty, more than one line, or longer than LONGEST_WHY.
    """
    text = str(why or "").strip()
    if not text or "\n" in text or len(text) > LONGEST_WHY:
        raise DoorError(f"--why is one line of at most {LONGEST_WHY} characters")
    return text


def path_of(plan: ApprovedPlan, path: str) -> str:
    """The path from the plan's root of an absolute file path the plan may be widened with.

    Args:
        plan: the plan in force; its root is read.
        path: an absolute file path.

    Returns:
        The path from the plan's root with forward slashes.

    Raises:
        DoorError: not absolute, a folder, outside the plan's root, or under .git.
    """
    if not os.path.isabs(str(path)):
        raise DoorError(f"{path} is not an absolute path")
    if os.path.isdir(path):
        raise DoorError(f"{path} is a folder: name a file")
    rel = relative(path, plan["root"])
    if rel is None:
        raise DoorError(f"{path} is outside the plan's root {plan['root']}")
    if ".git" in re.split(r"[\\/]", rel):
        raise DoorError(f"{path} is under .git, which no plan edits")
    return rel.replace("\\", "/")


def known(plan: ApprovedPlan, registry: dict[str, Behaviour], bid: str) -> None:
    """Check that a behaviour is named by the plan or the registry.

    Args:
        plan: the plan in force; its behaviors are read.
        registry: the plan's behaviour registry.
        bid: the behaviour id.

    Raises:
        DoorError: neither names it.
    """
    if bid not in registry and bid not in {b["id"] for b in plan.get("behaviors", [])}:
        raise DoorError(f"no behaviour {bid} in the plan or the registry")


def not_locked(port: PlanStore, sid: str, rel: str) -> None:
    """Refuse a file the orchestrator locked for this child session: an acceptance test of its card (acTests), which
    it must make pass and never change (utils/orchestra/locked.py); and, for a child with an issue, any file outside
    its scope, its card's change and tests (the scope of its ticket row and issue).

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        sid: the Claude Code session id.
        rel: the file's path from the plan's root (the child's unit folder).

    Raises:
        DoorError: the session is a child and the file is one of its card's acceptance tests.
    """
    role = (port.ticket(sid) or {}).get("child") or {}
    card = role.get("card") or {}
    if rel in (card.get("acTests") or []):
        raise DoorError(f"{rel} is an acceptance test the orchestrator locked for this child (plan {role.get('plan')}): "
                        "make it pass and never change it; ask the orchestrator if it is wrong")
    number = ((role.get("record") or {}).get("issue") or {}).get("number")
    if number and not matches(list(card.get("change") or []) + list(card.get("tests") or []), rel):
        raise DoorError(f"{rel} is outside the scope of issue #{number} (its change and tests): the orchestrator's "
                        "check refuses any other file; ask the orchestrator (run('orchestra', 'question')) if the card needs it")


def add_file(port: PlanStore, sid: str, plan: ApprovedPlan, path: str, behavior: str, why: Optional[str]) -> str:
    """The door `add file`: widen the plan with one file, for a behaviour; never a file locked for a child.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        sid: the Claude Code session id.
        plan: the plan in force.
        path: the file's absolute path.
        behavior: the id of the behaviour it serves (in the plan or the registry).
        why: the reason, one line.

    Returns:
        The text for the user: "<path> is a file of plan <id> now ([<behavior>])."

    Raises:
        DoorError: a bad path or reason, an unknown behaviour, or a locked acceptance test.
    """
    rel, text = path_of(plan, path), why_of(why)
    not_locked(port, sid, rel)
    known(plan, port.registry(plan), behavior)
    port.door(sid, plan, grants=[("add", os.path.abspath(path), f"[{behavior}] {text}")])
    return f"{rel} is a file of plan {plan['plan_id']} now ([{behavior}])."


def add_test(port: PlanStore, sid: str, plan: ApprovedPlan, target: str, behavior: str, what: Optional[str]) -> str:
    """The door `add test`: widen the plan with a test file and record it for a behaviour (pending until it exists).

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        sid: the Claude Code session id.
        plan: the plan in force.
        target: the test's absolute path, with "#name" for one test in it.
        behavior: the behaviour id (a.b-c).
        what: what the test checks.

    Returns:
        The text for the user: "behaviour <id>: test <test> added (active|pending)."

    Raises:
        DoorError: a bad path, behaviour id or what, or a named test missing from an existing file.
    """
    path, _, name = str(target).partition("#")
    rel = path_of(plan, path)
    not_locked(port, sid, rel)
    if not BEHAVIOR_ID.match(str(behavior or "")):
        raise DoorError(f"--behavior {behavior!r} is not a behaviour id (a.b-c)")
    if not str(what or "").strip():
        raise DoorError("--what says what the test checks (AC1: ...)")
    test = rel + (f"#{name}" if name else "")
    gone = test_missing(plan["root"], test)
    if name and os.path.isfile(path) and gone:
        raise DoorError(gone)
    status = "pending" if gone else "active"
    entry = {"what": str(what).strip(), "tests": [test], "status": status, "plan": plan["id"]}
    port.door(sid, plan, grants=[("add", os.path.abspath(path), f"[{behavior}] test")], behaviors=[("add", behavior, entry)])
    return f"behaviour {behavior}: test {test} added ({status})."


def drop_file(port: PlanStore, sid: str, plan: ApprovedPlan, path: str, why: Optional[str]) -> str:
    """The door `add drop-file`: take an unchanged file out of the plan.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        sid: the Claude Code session id.
        plan: the plan in force.
        path: the file's absolute path.
        why: the reason, one line.

    Returns:
        The text for the user: "<path> left plan <id>."

    Raises:
        DoorError: a bad path or reason, not a file of the plan, or the file is changed.
    """
    rel, text = path_of(plan, path), why_of(why)
    if not allows(plan, rel):
        raise DoorError(f"{rel} is not a file of the plan")
    if rel in port.changed_files(plan):
        raise DoorError(f"{rel} is changed: restore it (or delete a new one) before it leaves the plan")
    port.door(sid, plan, grants=[("drop", os.path.abspath(path), text)])
    return f"{rel} left plan {plan['plan_id']}."


def retire_test(port: PlanStore, sid: str, plan: ApprovedPlan, bid: str, why: Optional[str]) -> str:
    """The doors `add retire-test` and `behaviors retire`: retire an active or pending behaviour.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        sid: the Claude Code session id.
        plan: the plan in force.
        bid: the behaviour id.
        why: the reason, one line.

    Returns:
        The text for the user: "behaviour <id> is retired."

    Raises:
        DoorError: a bad reason, no such behaviour in the registry, or it is neither active nor pending.
    """
    text, registry = why_of(why), port.registry(plan)
    if bid not in registry:
        raise DoorError(f"no behaviour {bid} in the registry")
    if registry[bid]["status"] not in ("active", "pending"):
        raise DoorError(f"behaviour {bid} is {registry[bid]['status']}")
    port.door(sid, plan, behaviors=[("retire", bid, {"why": text})])
    return f"behaviour {bid} is retired."


def behaviors_add(port: PlanStore, sid: str, plan: ApprovedPlan, bid: str, what: Optional[str], how: Optional[str],
                  why: Optional[str], tests: Sequence[str]) -> str:
    """The door `behaviors add`: add an active behaviour whose tests all exist.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        sid: the Claude Code session id.
        plan: the plan in force.
        bid: the behaviour id (a.b-c).
        what: what it does.
        how: how it is proven.
        why: why it matters.
        tests: its tests, "file" or "file#name" from the plan's root.

    Returns:
        The text for the user: "behaviour <id> added (<n> test(s))."

    Raises:
        DoorError: a bad id, a missing field or test list, or a test that does not exist.
    """
    if not BEHAVIOR_ID.match(str(bid or "")):
        raise DoorError(f"{bid!r} is not a behaviour id (a.b-c)")
    if not all(str(x or "").strip() for x in (what, how, why)) or not tests:
        raise DoorError("a behaviour needs --what, --how, --why and --test")
    for test in tests:
        missing = test_missing(plan["root"], test)
        if missing:
            raise DoorError(missing)
    entry = {"what": what, "how": how, "why": why, "tests": list(tests), "status": "active", "plan": plan["id"]}
    port.door(sid, plan, behaviors=[("add", bid, entry)])
    return f"behaviour {bid} added ({len(tests)} test(s))."


def behaviors_list(port: PlanStore, plan: ApprovedPlan) -> str:
    """The door `behaviors list`: the plan's behaviour registry, one line each.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        plan: the plan in force.

    Returns:
        "<id> [<status>] <what> - <tests>" per behaviour, sorted by id; a sentence when there is none.
    """
    registry = port.registry(plan)
    if not registry:
        return "No behaviour in the registry of this plan."
    return "\n".join(f"{bid} [{b['status']}] {b.get('what', '')} - {', '.join(b['tests']) or 'no test'}"
                     for bid, b in sorted(registry.items()))


def behaviors_check(port: PlanStore, plan: ApprovedPlan) -> tuple[list[str], int]:
    """(lines, how many active behaviours lost a test).

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        plan: the plan in force.

    Returns:
        (one "<id>: <problem>" line per missing test, or one line saying all are there; the number of problems).
    """
    gone = [f"{bid}: {problem}" for bid, b in sorted(port.registry(plan).items()) if b["status"] == "active"
            for problem in (test_missing(plan["root"], t) for t in b["tests"]) if problem]
    return (gone or ["Every active behaviour has its tests."]), len(gone)
