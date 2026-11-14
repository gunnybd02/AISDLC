"""The desk of a plan (docs 04, section 2): a plan is data. clean keeps the known items in their shape, normalize fills
what follows from them (behaviours from steps and tests, files and tests from steps and code, services of a light
plan), check names every problem, merge applies a revision. A plan with problems is not kept.

tier: full when any of steps, behaviors, code, test, children is given, else light. A light plan needs a title (when
new), what (or overview.need) and files; a full plan needs services, what, files, checks, assumptions, notDoing and
risks, and on a new plan an overview and code too.

Paths are relative to the plan's root (the folder the MCP server runs in), inside it, never in .git."""
import re
import secrets
import time

from harness.utils.plan.tickets import base36

KEYS = ("title", "overview", "code", "test", "services", "branch", "what", "files", "tests", "checks", "commit",
        "steps", "behaviors", "network", "commands", "children", "teamSkills", "assumptions", "notDoing", "risks")
POINTS = ("what", "checks", "assumptions", "notDoing", "risks")
RECORD = ("title", "overview", "code", "checks", "assumptions", "notDoing", "risks")
FULL_MARKS = ("steps", "behaviors", "code", "test", "children")
FULL_REQUIRED = ("services", "what", "files", "checks", "assumptions", "notDoing", "risks")
OVERVIEW = ("problem", "need", "how", "accept")
STANDALONE = ("none", "agent-code")
MAX_POINTS, MAX_POINT, MAX_CODE, MAX_OVERVIEW = 10, 200, 600, 5
BEHAVIOR_ID = re.compile(r"^[a-z][a-z0-9]*([.-][a-z0-9]+)*$")
STEP_ID = re.compile(r"^s(\d+)\.")
BRANCH_RE = re.compile(r"^(?!-)(?!.*\.\.)[A-Za-z0-9._/-]+$")
HOST_RE = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*$")
COMMAND_RE = re.compile(r"^twg\s[^;&|<>`]*$")
CHILD_NAME = re.compile(r"^[a-z0-9-]{1,40}$")
CODE_TITLE = re.compile(r"^(pd-\S+|[0-9a-f]{7,})$", re.I)
ABSOLUTE = re.compile(r"^([A-Za-z]:|[\\/~])")


def new_id():
    return f"pd-{base36(int(time.time() * 1000))}-{secrets.token_hex(3)}"


def one_line(text):
    return " ".join(str(text).split())


def strings(value):
    """A list of stripped non-empty strings (one string is a list of one), deduped in order."""
    items = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return list(dict.fromkeys(s.strip().replace("\\", "/") for s in items if isinstance(s, str) and s.strip()))


def clean(raw):
    """The known items of raw in their plain shape; optional items only when given."""
    out = {}
    for key in KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if key in ("title", "branch") and isinstance(value, str):
            value = one_line(value)
        elif key == "commit" and isinstance(value, str):
            value = one_line(re.sub(r"[`*_|]", "", value))
        elif key in POINTS or key in ("services", "files", "tests", "teamSkills", "commands"):
            value = strings(value) if key != "commands" else [one_line(c) for c in strings(value)]
        out[key] = value
    return out


def normalize(items):
    """What follows from the items: step and test behaviours, files and tests of steps and code, light services."""
    out = dict(items)
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


def merge(old, changes):
    """A revision: each given item replaces the old one whole; without steps, new files and tests join the last step."""
    out = {**old, **changes}
    if "steps" not in changes and old.get("steps"):
        steps = [dict(s) for s in old["steps"]]
        last = steps[-1]
        for key in ("files", "tests"):
            new = [p for p in strings(changes.get(key, [])) if p not in strings(old.get(key, []))]
            if new:
                last[key] = strings(last.get(key, []) + new)
        out["steps"] = steps
    return out


def tier(items):
    return "full" if any(items.get(k) for k in FULL_MARKS) else "light"


def unknown(raw):
    return [f"unknown item {k}" for k in raw if k not in KEYS]


def check(items, need_title=True, keys=None, units=()):
    """Every problem of the items: the form of each item (only those in keys, when given), then what the tier needs."""
    look = set(items) if keys is None else set(keys)
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


def title_problems(title):
    if not isinstance(title, str) or not title.strip():
        return ["title is needed: one line, 3 to 80 characters, two words at least"]
    t = one_line(title)
    if not 3 <= len(t) <= 80 or len(t.split()) < 2:
        return ["title is one line of 3 to 80 characters, two words at least"]
    if CODE_TITLE.match(t) or '"' in t:
        return ["title is words, not a code, and holds no double quote (the form question quotes it)"]
    return []


def points(value, units=(), most=MAX_POINTS):
    if not isinstance(value, list) or not all(isinstance(p, str) and p.strip() for p in value):
        return ["a list of points (strings)"]
    if len(value) > most:
        return [f"at most {most} points"]
    return [f"a point of more than {MAX_POINT} characters" for p in value if len(p) > MAX_POINT][:1]


def path_problems(value, units=(), required=False):
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


def overview_problems(value, units=()):
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


def code_problems(value, units=()):
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


def test_problems(value, units=()):
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


def services_problems(value, units=()):
    if not isinstance(value, list) or not value:
        return ["a list of units, or none, or agent-code"]
    if any(s in STANDALONE for s in value) and len(value) > 1:
        return ["none and agent-code stand alone"]
    return [f"{s} is no declared unit" for s in value if s not in STANDALONE and s not in units]


def steps_problems(value, units=()):
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


def behaviors_problems(value, units=()):
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


def network_problems(value, units=()):
    if not isinstance(value, list) or len(value) > 20:
        return ["a list of at most 20 {host, port, why}"]
    return [f"{n.get('host') if isinstance(n, dict) else n!r}: a host name (no scheme, path or port), a port 1-65535 "
            "and why" for n in value if not (isinstance(n, dict) and isinstance(n.get("host"), str)
                                             and HOST_RE.match(n["host"]) and isinstance(n.get("port"), int)
                                             and 1 <= n["port"] <= 65535 and str(n.get("why") or "").strip())]


def commands_problems(value, units=()):
    if len(value) > 30:
        return ["at most 30 lines"]
    return [f"{c!r} is one twg line of at most 400 characters, no ; & | < > or backtick"
            for c in value if len(c) > 400 or not COMMAND_RE.match(c)]


def children_problems(value, units=()):
    if not isinstance(value, list):
        return ["a list of {name, unit, goal, ac, read, change, tests, actions}"]
    out, seen = [], set()
    for c in value:
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or not CHILD_NAME.match(c["name"]):
            out.append("each child has a name of a-z, 0-9 and -, 40 at most")
            continue
        if c.get("unit") not in STANDALONE and c.get("unit") not in units:
            out.append(f"{c['name']}: unit {c.get('unit')!r} is neither the home nor a declared unit")
        elif c.get("unit") in seen:
            out.append(f"{c['name']}: one child per unit")
        seen.add(c.get("unit"))
        if not isinstance(c.get("goal"), str) or not c["goal"].strip() or len(c["goal"]) > MAX_POINT:
            out.append(f"{c['name']}: goal is at most {MAX_POINT} characters")
        ac = c.get("ac")
        if not isinstance(ac, list) or not 1 <= len(ac) <= 6 or not all(
                isinstance(a, str) and len(a) <= 120 and len(re.findall(r"[A-Za-z\u00c0-\u1ef9]{3,}", a)) >= 2 for a in ac):
            out.append(f"{c['name']}: ac is 1 to 6 checks of at most 120 characters, two words at least")
        for key in ("read", "change", "tests"):
            if len(c.get(key, [])) > 8 or path_problems(c.get(key, [])):
                out.append(f"{c['name']}: {key} is at most 8 paths")
        if set(c.get("actions", [])) - {"push"}:
            out.append(f"{c['name']}: the only action a child may take is push")
    return out


def branch_problems(value, units=()):
    return [] if isinstance(value, str) and BRANCH_RE.match(value) else [f"{value!r} is not a branch name"]


CHECKS = {**{k: points for k in POINTS}, "overview": overview_problems, "code": code_problems,
          "test": test_problems, "services": services_problems, "steps": steps_problems,
          "behaviors": behaviors_problems, "network": network_problems, "commands": commands_problems,
          "children": children_problems, "branch": branch_problems, "teamSkills": points,
          "files": lambda v, u: path_problems(v, required=True), "tests": path_problems,
          "commit": lambda v, u: [] if isinstance(v, str) else ["the commit message"]}
