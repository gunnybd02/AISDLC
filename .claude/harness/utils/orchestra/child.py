"""Child: a session opened from a brief (utils/orchestra/brief.py) is a child of a delegated plan (docs/05b-orchestra-
cloud.md part 2). Its role comes from its first prompt only: the brief's first words and its card block. A later
prompt (a message from another session among them) never makes a session a child.

- bind: at the first prompt, keep the role on the session's ticket (child).
- role_of: the role of a session, from its ticket.
- card_plan: the plan the child's take opens, made from its card: the goal, the change and test paths, one behaviour
  per criterion with the id the brief gave."""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Optional

from harness.utils.orchestra.brief import CARD_CLOSE, CARD_OPEN, HEAD, branch
from harness.utils.orchestra.card import HOME, HOME_SPEC, behaviour_id
from harness.utils.plan import desk, tickets
from harness.utils.plan.item_checks import STANDALONE, one_line
from harness.utils.shapes import ChildRole, PlanItems, Ticket

START = "You are " + HEAD[:HEAD.index(" \"")]  # You are child session
FIRST = re.compile(r'^You are child session "(?P<name>[a-z0-9][a-z0-9-]{0,39})" of the delegated plan (?P<plan>\d+)')
BLOCK = re.compile(re.escape(CARD_OPEN) + r"\n(?P<body>\{.*\})\n" + re.escape(CARD_CLOSE), re.S)


def parse(text: str) -> Optional[ChildRole]:
    """The role a brief gives: its first words name the child and the plan, and its card block (one JSON object) says
    the same child and plan, with the parent's session, the branch, the card, the behaviour ids, the plan branch it
    starts from (start, "" for the unit's base), and its issue, ticket file and draft pull request (record, {} when
    the brief names none).

    Args:
        text: a prompt.

    Returns:
        The ChildRole, or None when the prompt is no brief or its parts disagree.
    """
    head, block = FIRST.match(text.lstrip()), BLOCK.search(text)
    if not head or not block:
        return None
    try:
        body = json.loads(block.group("body"))
    except ValueError:
        return None
    name, plan = head.group("name"), int(head.group("plan"))
    card = body.get("card") if isinstance(body, dict) else None
    if not isinstance(card, dict) or card.get("name") != name or body.get("plan") != plan \
            or body.get("branch") != branch(plan, name) or not str(body.get("parent", "")).strip():
        return None
    unit = body.get("unit") if isinstance(body.get("unit"), dict) else {}
    unit = {**HOME_SPEC, **{k: v for k, v in unit.items() if k in HOME_SPEC}}
    if not isinstance(unit["path"], str) or ".." in unit["path"].replace("\\", "/").split("/") \
            or unit["path"].startswith("/") or not isinstance(unit["verify"], list):
        return None
    start = body.get("start") if isinstance(body.get("start"), str) else ""
    record = {k: body[k] for k in ("issue", "ticket", "pr") if isinstance(body.get(k), dict)}
    return {"name": name, "plan": plan, "draft": str(body.get("draft", "")), "parent": str(body["parent"]),
            "branch": body["branch"], "card": card, "unit": unit, "start": start, "record": record,
            "behaviours": [behaviour_id(plan, name, n) for n in range(1, len(card.get("ac", [])) + 1)]}


def bind(con: sqlite3.Connection, sid: str, text: str) -> Optional[ChildRole]:
    """Make the session a child when this prompt is its first and a brief: its ticket (a new one when it has none)
    keeps the role. A session that already has a role or a plan in force is left as it is.

    Args:
        con: the connection of the transaction (the prompt is already kept in pl_prompts).
        sid: the session.
        text: the prompt, whole.

    Returns:
        The role kept, or None.
    """
    if not text.lstrip().startswith(START):
        return None
    if (con.execute("SELECT COUNT(*) FROM pl_prompts WHERE sid = ?", (sid,)).fetchone()[0] or 0) > 1:
        return None
    role = parse(text)
    ticket = tickets.latest(con, sid)
    if role is None or (ticket and (ticket.get("child") or tickets.approved_plan(ticket))):
        return None
    base = ticket if ticket and ticket.get("state") == tickets.OPEN else tickets.blank(sid)
    tickets.save(con, {**base, "child": role})
    return role


NOT_IN_A_CHILD = ("a child session {what}: nobody is at its keyboard. Hand back instead "
                  "(run('orchestra', 'handback', {{...}})), or ask the orchestrator (run('orchestra', 'question'))")


def refusal(ticket: Optional[Ticket], what: str) -> str:
    """Why a child may not do what: the text of the refusal, or "" for a session that is no child.

    Args:
        ticket: the session's ticket.
        what: what it may not do, e.g. "never presents a plan of its own".

    Returns:
        The refusal, or "".
    """
    return NOT_IN_A_CHILD.format(what=what) if role_of(ticket) else ""


def role_of(ticket: Optional[Ticket]) -> Optional[ChildRole]:
    """The child role a ticket holds.

    Args:
        ticket: a session's ticket, or None.

    Returns:
        The ChildRole, or None for a session that is no child.
    """
    role = (ticket or {}).get("child")
    return role if isinstance(role, dict) and role.get("name") else None


def unit_root(role: ChildRole, repo: str) -> str:
    """The folder a child's plan is rooted in: its unit's folder in the repository's clone.

    Args:
        role: the child's role.
        repo: the root of the clone.

    Returns:
        The folder, with forward slashes.
    """
    path = role.get("unit", HOME_SPEC)["path"].replace("\\", "/").strip("/")
    return repo.rstrip("/") if path in ("", ".") else f"{repo.rstrip('/')}/{path}"


def card_plan(role: ChildRole, root: str) -> PlanItems:
    """The plan a child opens with take, made from its card (spec 05 section 6): title "<name>: <goal>", the goal as
    what, need and the commit, the change paths as files and code, the test paths as tests, one step, one behaviour
    per criterion (id p<plan>.<name>.ac<n>, what "AC<n>: <criterion>", the first locked acceptance test when the card
    has one, else its first test; a locked test is never a file or test of the plan, so it cannot be edited), and the
    fixed checks, assumption, not doing and risk; verify, the unit's test command, when its unit names one (set here,
    by the server, never by the model).

    Args:
        role: the child's role.
        root: the folder the plan's paths are relative to (the unit's folder: unit_root).

    Returns:
        The items, normalized, with their root.
    """
    card, name = role["card"], role["name"]
    goal, change, tests = one_line(card["goal"]), list(card.get("change", [])), list(card.get("tests", []))
    acs, proof = list(card.get("ac", [])), (list(card.get("acTests", [])) or tests or [""])[0]  # a locked test proves
    unit = card.get("unit", HOME)
    items: dict[str, Any] = {
        "title": re.sub(r'["]', "", f"{name}: {goal}")[:80].strip(),
        "overview": {"problem": [goal[:200]], "need": [goal[:200]],
                     "how": [f"change {', '.join(change)}"[:200], f"prove it with {', '.join(tests) or 'its tests'}"[:200]],
                     "accept": [a[:200] for a in acs[:5]]},
        "code": [{"file": f, "code": "", "reason": "the parent plan names this file for the goal"} for f in change],
        "services": ["agent-code"] if unit in (HOME,) + STANDALONE else [unit],
        "what": [goal[:200]], "files": change, "tests": tests,
        "steps": [{"commit": re.sub(r"[`*_|]", "", goal)[:200], "files": change, "tests": tests,
                   "points": ["change the files of the card", "prove each AC with a registered test"]}],
        "behaviors": [{"id": role["behaviours"][n - 1], "what": f"AC{n}: {a}"[:200], "how": "a registered test",
                       "why": goal[:200], "test": proof, "step": 1}
                      for n, a in enumerate(acs, 1)],
        "checks": ["the registered tests of each AC pass in verify"],
        "assumptions": [f"the card of the parent plan {role['plan']} is the whole scope"],
        "notDoing": ["anything outside the card"], "risks": ["a case the AC does not name stays unchecked"],
        "branch": role["branch"],
    }
    verify = role.get("unit", HOME_SPEC).get("verify") or []
    return {**desk.normalize(items), **({"verify": list(verify)} if verify else {}), "root": root}
