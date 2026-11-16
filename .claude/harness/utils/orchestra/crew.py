"""Crew: the single writer of the children's state (docs/05-orchestra.md sections 6 and 7). The parent's delegated
ticket holds the grant and the crew (one CrewEntry per started child); every change of a child's state is also one
row of the story, pl_children, which is never changed in place.

- open_delegated: the user approved a plan with children; its ticket takes the grant, keeps the crew of an earlier
  revision, and a "pending" story row is written for each child not yet in the crew.
- room: whether the parent may start a child now (delegated plan in force, a child of it, not started, under the cap).
- start: the child's cloud session exists; its entry is written as running.

In the cloud harness code cannot open a session (only the model's create_session can), so a child counts as running
only once its session id comes back (orchestra started): a failed create_session leaves no ghost."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Optional

from harness.utils.orchestra import card as cards
from harness.utils.plan import tickets
from harness.utils.shapes import ApprovedPlan, Card, CrewEntry, Ticket

CAP = 3
PENDING, RUNNING, HANDED_BACK = "pending", "running", "handed back"
ACCEPTED, FORGOTTEN, RELEASED, REMOVED = "accepted", "forgotten", "released", "removed"
ENDED = (ACCEPTED, FORGOTTEN, RELEASED, REMOVED)
BUSY = (RUNNING, "reserved")


def now() -> int:
    """The time now in ms.

    Returns:
        Milliseconds since the epoch.
    """
    return int(time.time() * 1000)


def delegated(ticket: Optional[Ticket]) -> Optional[ApprovedPlan]:
    """The delegated plan in force under a ticket: open, with a plan that has children.

    Args:
        ticket: a ticket, or None.

    Returns:
        The ApprovedPlan, or None when the ticket holds no delegated plan in force.
    """
    plan = tickets.approved_plan(ticket)
    return plan if plan and plan.get("children") else None


def story(con: sqlite3.Connection, plan: int, child: Card, state: str, rounds: int = 0, sid: str = "",
          model: str = "") -> None:
    """Append one row of a child's story to pl_children.

    Args:
        con: the connection of the transaction.
        plan: the parent plan's number.
        child: the child's card (name, unit, goal, ac).
        state: the state it enters.
        rounds: how many times it was sent back.
        sid: its session id, once known.
        model: the model it was started with.
    """
    con.execute("INSERT INTO pl_children (uid, plan_id, name, unit, state, round, sid, model, goal, ac, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, plan, child["name"], child.get("unit", ""), state, rounds, sid, model,
                 child.get("goal", ""), json.dumps(child.get("ac", []), ensure_ascii=False), now()))


def open_delegated(con: sqlite3.Connection, sid: str) -> Optional[Ticket]:
    """Make the session's ticket a delegated one, after its plan with children opened (utils/plan/opening.py): the
    grant of the plan, the crew it already had (a revision keeps its children), and a pending story row for each child
    neither in the crew nor in the story of this plan number.

    Args:
        con: the connection of the transaction.
        sid: the parent's session.

    Returns:
        The ticket saved; None when the plan in force has no children.
    """
    ticket = tickets.latest(con, sid)
    plan = delegated(ticket)
    if plan is None:
        return None
    crew = dict(ticket.get("crew") or {})
    told = {name for (name,) in con.execute("SELECT name FROM pl_children WHERE plan_id = ?", (plan["id"],))}
    for child in plan["children"]:
        if child["name"] not in crew and child["name"] not in told:
            story(con, plan["id"], child, PENDING)
    return tickets.save(con, {**ticket, "grant": cards.grant(plan), "crew": crew})


def blocks_other(ticket: Optional[Ticket], plan_id: Optional[str] = None) -> str:
    """Why the session may not present or approve another plan: a delegated plan runs in it (section 5.4), and
    approving another plan would close it and orphan its children. A revision of that plan (plan_id its draft) is
    allowed.

    Args:
        ticket: the session's ticket.
        plan_id: the desk id of the plan to approve; None when a new plan is presented.

    Returns:
        The reason, or "" when nothing blocks.
    """
    plan = delegated(ticket)
    if plan is None or (plan_id is not None and plan_id == ticket.get("draft")):
        return ""
    return (f"the delegated plan {ticket.get('draft')} (plan {plan['id']}) runs in this session: finish it first "
            "(the children hand back, then it closes) or revise it with plan_revise")


def store_tag(ticket: Optional[Ticket]) -> str:
    """The plan marker of a session's copies in the store: "orch.<plan id>.<child name>" for a child,
    "orch.<plan id>.parent" for the parent of a delegated plan (open or closed), "" otherwise.

    Args:
        ticket: the session's newest ticket.

    Returns:
        The marker, or "".
    """
    role = (ticket or {}).get("child")
    if isinstance(role, dict) and role.get("draft") and role.get("name"):
        return f"orch.{role['draft']}.{role['name']}"
    plan = (ticket or {}).get("plan") or {}
    return f"orch.{ticket['draft']}.parent" if plan.get("children") and ticket.get("draft") else ""


def running(ticket: Ticket) -> list[str]:
    """The children of the crew that run now (running or reserved).

    Args:
        ticket: the parent's delegated ticket.

    Returns:
        Their names, in the crew's order.
    """
    return [name for name, entry in (ticket.get("crew") or {}).items() if entry.get("state") in BUSY]


def room(ticket: Optional[Ticket], name: str) -> Card:
    """The card of a child the parent may start now: a delegated plan the user approved is in force, the name is one of
    its children, the child has not started (or was forgotten), and fewer than CAP children run.

    Args:
        ticket: the parent's ticket.
        name: the child's name.

    Returns:
        The child's Card.

    Raises:
        ValueError: the reason it may not start, for the model.
    """
    plan = delegated(ticket)
    if plan is None:
        raise ValueError("no delegated plan is in force in this session: present a plan with children and ask the "
                         "user with the form first")
    card = cards.card_of(plan, name)
    if card is None:
        raise ValueError(f"{name} is no child of plan {plan['id']}: its children are "
                         + ", ".join(c["name"] for c in plan["children"]))
    entry = (ticket.get("crew") or {}).get(name)
    if entry and entry.get("state") != FORGOTTEN:
        raise ValueError(f"{name} has started already (state {entry.get('state')}, session {entry.get('sid')})")
    busy = running(ticket)
    if len(busy) >= CAP:
        raise ValueError(f"{CAP} children run already ({', '.join(busy)}): accept or forget one before you spawn "
                         "another")
    return card


def start(con: sqlite3.Connection, sid: str, name: str, child_sid: str, model: str = "") -> CrewEntry:
    """Record a started child: its crew entry as running with its cloud session, and a running story row. Every check
    of room is made again inside the transaction, and the session may be the child of no other crew entry.

    Args:
        con: the connection of the transaction.
        sid: the parent's session.
        name: the child's name.
        child_sid: the child's cloud session id.
        model: the model it was started with, if one was named.

    Returns:
        The CrewEntry written.

    Raises:
        ValueError: the reason it may not be recorded.
    """
    ticket = tickets.latest(con, sid)
    card = room(ticket, name)
    if child_sid == sid:
        raise ValueError("that is this session: give the new child's session id")
    taken = [n for n, e in (ticket.get("crew") or {}).items() if e.get("sid") == child_sid and e.get("state") not in ENDED]
    if taken:
        raise ValueError(f"session {child_sid} is the child {taken[0]} already: one session is one child")
    entry: CrewEntry = {"unit": card["unit"], "sid": child_sid, "state": RUNNING, "backs": 0, "checkedAt": None,
                        "adopted": False, "model": model, "reportSid": sid, "at": now(), "sentBackAt": None, "sent": []}
    plan = delegated(ticket)
    story(con, plan["id"], card, RUNNING, sid=child_sid, model=model)
    tickets.save(con, {**ticket, "crew": {**(ticket.get("crew") or {}), name: entry}})
    return entry


def status(ticket: Optional[Ticket]) -> str:
    """The state of a delegated plan: "Plan N: x of y accepted", then one line per child (name | unit | state |
    session | rounds); a child not yet started is pending.

    Args:
        ticket: the parent's ticket.

    Returns:
        The text; a sentence when no delegated plan is in force.
    """
    plan = delegated(ticket)
    if plan is None:
        return "No delegated plan is in force in this session."
    crew = ticket.get("crew") or {}
    done = sum(1 for e in crew.values() if e.get("state") == ACCEPTED)
    lines = [f"Plan {plan['id']}: {done} of {len(plan['children'])} accepted; {len(running(ticket))} of {CAP} may run."]
    for child in plan["children"]:
        entry = crew.get(child["name"], {})
        rounds = f", sent back {entry['backs']}x" if entry.get("backs") else ""
        lines.append(f"- {child['name']} | {child.get('unit')} | {entry.get('state', PENDING)}{rounds} | "
                     f"session {entry.get('sid') or '-'}")
    return "\n".join(lines)
