"""Cleanup: the end of a delegated plan's children (docs/05b-orchestra-cloud.md part 4).

- release: a child's session goes back to the user; it leaves the crew and may keep working alone.
- remove: which child sessions are archived is the user's word, each time. With no pass, remove answers ONE checklist
  form (the children that no longer run, at most 4 a question); the user ticks; each tick is a one-use pass kept in
  pl_asks; the next remove marks exactly the ticked children removed and says the archive_session call of each (harness
  code cannot archive a cloud session; the parent's model does).
- digest: one line per child, from the crew."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from typing import TYPE_CHECKING, Any

from harness.utils.orchestra import crew
from harness.utils.orchestra.review import ReviewError, child_of, set_entry
from harness.utils.shapes import PlanStore, Ticket

if TYPE_CHECKING:
    from harness.utils.ledger.recorder import Recorder

QUESTION = re.compile(r"^Remove the child sessions of plan (?P<plan>\d+) \[(?P<code>r[0-9a-f]{12})\]\?$")
DONE = (crew.ACCEPTED, crew.FORGOTTEN, crew.RELEASED)
PER_QUESTION = 4


def release(port: PlanStore, sid: str, name: str, why: str) -> str:
    """Give a child's session back to the user: it is released and leaves the crew; its work and plan stay its own.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        why: the reason.

    Returns:
        What was done.

    Raises:
        ReviewError: no such child, ended, or no reason.
    """
    text = " ".join(str(why).split())
    if not text:
        raise ReviewError("say why the session is released")
    _, card, entry = child_of(port, sid, name)
    set_entry(port, sid, name, card, {"state": crew.RELEASED, "releasedWhy": text[:300]}, crew.RELEASED)
    return (f"{name} released: its session {entry['sid']} is the user's again, with its branch and its plan. It is "
            "no longer checked, accepted or merged by this plan.")


def removable(ticket: Ticket) -> list[str]:
    """The children of the delegated plan whose sessions may be archived: ended (accepted, forgotten, released) and
    not removed yet, in the plan's order.

    Args:
        ticket: the parent's ticket.

    Returns:
        Their names.
    """
    team = ticket.get("crew") or {}
    return [c["name"] for c in ticket["plan"].get("children", []) if team.get(c["name"], {}).get("state") in DONE]


def code_of(plan: int, names: list[str]) -> str:
    """The code of one checklist: of this plan and exactly these children.

    Args:
        plan: the plan's number.
        names: the children it lists.

    Returns:
        "r" and 12 hex characters.
    """
    return "r" + hashlib.sha256(json.dumps([plan, names]).encode("utf-8")).hexdigest()[:12]


def checklist(ticket: Ticket) -> list[dict[str, Any]]:
    """The checklist form: one multi-select question per PER_QUESTION removable children.

    Args:
        ticket: the parent's ticket.

    Returns:
        The questions of one AskUserQuestion call ({question, header, multiSelect, options}).
    """
    team, plan, out = ticket.get("crew") or {}, ticket["plan"]["id"], []
    names = removable(ticket)
    for i in range(0, len(names), PER_QUESTION):
        part = names[i:i + PER_QUESTION]
        out.append({"question": f"Remove the child sessions of plan {plan} [{code_of(plan, part)}]?",
                    "header": "Remove", "multiSelect": True,
                    "options": [{"label": n, "description": f"{team[n]['state']}; session {team[n].get('sid')}; "
                                                            "archived when ticked"} for n in part]})
    return out


def removal_accepts(port: PlanStore, answers: dict[str, str]) -> list[str]:
    """Keep a one-use pass for each child the user ticked in a remove checklist; the notes for the model.

    Args:
        port: the harness ledger.
        answers: {form question: the labels the user chose, joined by ", "} of an AskUserQuestion call.

    Returns:
        One note per checklist answered; [] when none was.
    """
    notes = []
    for q, label in (answers or {}).items():
        m = QUESTION.match(str(q))
        if not m:
            continue
        names = [n.strip() for n in str(label).split(",") if re.match(r"^[a-z0-9][a-z0-9-]{0,39}$", n.strip())]
        for name in names:
            port.write(lambda con, rec, key=f"{m['code']}:{name}": con.execute(
                "INSERT OR REPLACE INTO pl_asks (sid, key, at, used) VALUES ('', ?, ?, 0)",
                (key, int(time.time() * 1000))))
        notes.append(f"GATE: the user ticked {', '.join(names) or 'no child'} to remove [{m['code']}]; run "
                     "run('orchestra', 'remove', {}) again, once.")
    return notes


def remove(port: PlanStore, sid: str) -> str:
    """Remove the children the user ticked; with no tick yet, answer the checklist form to ask.

    Args:
        port: the ledger port.
        sid: the parent's session.

    Returns:
        The checklist to ask, or the children removed and the archive_session call of each.

    Raises:
        ReviewError: no delegated plan, or no child that may be removed.
    """
    ticket = port.ticket(sid)
    if ticket is None or not ticket.get("crew") or not ticket.get("plan"):
        raise ReviewError("no delegated plan with children in this session")
    names, plan = removable(ticket), ticket["plan"]["id"]
    if not names:
        raise ReviewError("no child may be removed: a child must have ended (accepted, forgotten or released)")
    keys = {n: f"{code_of(plan, names[i - i % PER_QUESTION:i - i % PER_QUESTION + PER_QUESTION])}:{n}"
            for i, n in enumerate(names)}

    def take(con: sqlite3.Connection, rec: Recorder) -> list[str]:
        ticked = [n for n, k in keys.items()
                  if con.execute("SELECT 1 FROM pl_asks WHERE sid = '' AND key = ? AND used = 0", (k,)).fetchone()]
        for n in ticked:
            con.execute("UPDATE pl_asks SET used = 1 WHERE sid = '' AND key = ?", (keys[n],))
        return ticked
    ticked = port.write(take)
    if not ticked:
        form = json.dumps({"questions": checklist(ticket)}, ensure_ascii=False)
        return ("Which child sessions are archived is the user's word. Ask now with AskUserQuestion exactly this, "
                f"and never fill in the answer: {form}. Then run('orchestra', 'remove', {{}}) again.")
    team, lines = ticket["crew"], []
    for name in ticked:
        card = next(c for c in ticket["plan"]["children"] if c["name"] == name)
        set_entry(port, sid, name, card, {"state": crew.REMOVED}, crew.REMOVED)
        lines.append(f"- {name}: mcp__claude-code-remote__archive_session {{\"session_id\": \"{team[name]['sid']}\"}}")
    return "Removed; archive each session now:\n" + "\n".join(lines)


def digest(port: PlanStore, sid: str) -> str:
    """One line per child of the delegated plan: state, rounds, session, branch, last check, pull request, merge.

    Args:
        port: the ledger port.
        sid: the parent's session.

    Returns:
        The digest; a sentence when there is no delegated plan.
    """
    ticket = port.ticket(sid)
    if not ticket or not ticket.get("plan") or not ticket["plan"].get("children"):
        return "No delegated plan in this session."
    plan, team = ticket["plan"], ticket.get("crew") or {}
    lines = [f"Plan {plan['id']} ({ticket.get('draft')}), {ticket.get('state')}: {len(plan['children'])} children."]
    for card in plan["children"]:
        e = team.get(card["name"], {})
        check = e.get("lastCheck") or {}
        pr = e.get("pr") or {}
        lines.append(" | ".join([card["name"], e.get("state", crew.PENDING), f"rounds {e.get('backs', 0)}",
                                 f"session {e.get('sid') or '-'}", f"orch/p{plan['id']}/{card['name']}",
                                 "check " + ("green" if check.get("green") else "red" if check else "-"),
                                 f"PR #{pr['number']}" if pr else "PR -",
                                 "merged" if e.get("merged") else "not merged"]))
    return "\n".join(lines)

