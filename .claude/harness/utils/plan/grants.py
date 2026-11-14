"""The CLI doors that widen or shrink an approved plan without a new approval (docs 04, section 4), and the behaviour
registry they keep. Each door judges its own arguments and refuses with why (DoorError); it writes chained rows only:
pl_file_grants (add, drop) and pl_behaviors (add, retire). A wider change (a unit, a host, a step) is plan_revise.

A behaviour of the registry is {what, how, why, tests: [file or file#name], status, step}; rows replay in order: add
merges and unions tests, retire and skip set the status (active, pending, skipped, retired)."""
import json
import os
import re

from harness.utils.plan.desk import BEHAVIOR_ID
from harness.utils.plan.files import allows, relative

LONGEST_WHY = 200


class DoorError(ValueError):
    pass


def replay(rows):
    """{id: behaviour} from the pl_behaviors rows (op, id, entry), in the order they were written."""
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


def test_missing(root, test):
    """Why a test (file or file#name, from the root) is missing, or "": no file, or no test of that name in it."""
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


def why_of(why):
    text = str(why or "").strip()
    if not text or "\n" in text or len(text) > LONGEST_WHY:
        raise DoorError(f"--why is one line of at most {LONGEST_WHY} characters")
    return text


def path_of(plan, path):
    """The path from the plan's root of an absolute file path the plan may be widened with."""
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


def known(plan, registry, bid):
    if bid not in registry and bid not in {b["id"] for b in plan.get("behaviors", [])}:
        raise DoorError(f"no behaviour {bid} in the plan or the registry")


def add_file(port, sid, plan, path, behavior, why):
    rel, text = path_of(plan, path), why_of(why)
    known(plan, port.registry(plan), behavior)
    port.door(sid, plan, grants=[("add", os.path.abspath(path), f"[{behavior}] {text}")])
    return f"{rel} is a file of plan {plan['plan_id']} now ([{behavior}])."


def add_test(port, sid, plan, target, behavior, what):
    path, _, name = str(target).partition("#")
    rel = path_of(plan, path)
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


def drop_file(port, sid, plan, path, why):
    rel, text = path_of(plan, path), why_of(why)
    if not allows(plan, rel):
        raise DoorError(f"{rel} is not a file of the plan")
    if rel in port.changed_files(plan):
        raise DoorError(f"{rel} is changed: restore it (or delete a new one) before it leaves the plan")
    port.door(sid, plan, grants=[("drop", os.path.abspath(path), text)])
    return f"{rel} left plan {plan['plan_id']}."


def retire_test(port, sid, plan, bid, why):
    text, registry = why_of(why), port.registry(plan)
    if bid not in registry:
        raise DoorError(f"no behaviour {bid} in the registry")
    if registry[bid]["status"] not in ("active", "pending"):
        raise DoorError(f"behaviour {bid} is {registry[bid]['status']}")
    port.door(sid, plan, behaviors=[("retire", bid, {"why": text})])
    return f"behaviour {bid} is retired."


def behaviors_add(port, sid, plan, bid, what, how, why, tests):
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


def behaviors_list(port, plan):
    registry = port.registry(plan)
    if not registry:
        return "No behaviour in the registry of this plan."
    return "\n".join(f"{bid} [{b['status']}] {b.get('what', '')} - {', '.join(b['tests']) or 'no test'}"
                     for bid, b in sorted(registry.items()))


def behaviors_check(port, plan):
    """(lines, how many active behaviours lost a test)."""
    gone = [f"{bid}: {problem}" for bid, b in sorted(port.registry(plan).items()) if b["status"] == "active"
            for problem in (test_missing(plan["root"], t) for t in b["tests"]) if problem]
    return (gone or ["Every active behaviour has its tests."]), len(gone)
