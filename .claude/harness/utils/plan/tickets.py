"""Tickets: one JSON body per ticket in pl_tickets (id, sid, seq, state, units, body, at); the newest seq of a session is
its ticket. A ticket runs a plan from its approval to its close:
  state      open | closed;  closeReason: delivered | abandoned | superseded
  phase      prepare (no plan) | execute | deliver
  plan       the ApprovedPlan {type, id (the plan number), plan_id (the desk id), rev, base, title, files, tests, root}
  draft, rootId   the desk id and the first plan number, kept across revisions
  step, commits, skips, doneSteps, priorCommits, spentPlan   the work done, and what a superseded ticket carried over
approved_plan(body) is the one rule for "a plan is in force". The functions take the open sqlite connection of a write
(or of a read), so a ticket changes in the same transaction as the rows around it."""
from __future__ import annotations

import itertools
import json
import sqlite3
from typing import Any, Optional

from harness.utils.contracts import DELIVER, EXECUTE, PHASES, PREPARE, now
from harness.utils.shapes import ApprovedPlan, PlanItems, PlanStore, Step, Ticket

OPEN, CLOSED = "open", "closed"
DELIVERED, ABANDONED, SUPERSEDED = "delivered", "abandoned", "superseded"
APPROVED_PLAN = "ApprovedPlan"
DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
_count = itertools.count()


CARRIED = ("child", "asks")  # what a new ticket of the session keeps (utils/orchestra/child.py)

def base36(n: int) -> str:
    """A whole number in base 36 (0-9, a-z).

    Args:
        n: a number, 0 or more.

    Returns:
        Its digits, "0" for 0.
    """
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = DIGITS[r] + out
        if not n:
            return out


def new_id() -> str:
    """A new ticket id, unique in this process.

    Returns:
        "t-<the time in ms, base 36>-<a counter>".
    """
    return f"t-{base36(now())}-{next(_count)}"


def blank(sid: str) -> Ticket:
    """A new ticket of a session: open, in prepare, with no plan and no work.

    Args:
        sid: the Claude Code session id.

    Returns:
        The ticket body, not saved.
    """
    return {"id": new_id(), "sid": sid, "state": OPEN, "phase": PREPARE, "plan": None, "draft": None, "rootId": None,
            "step": 0, "commits": [], "skips": 0, "doneSteps": [], "priorCommits": [], "closeReason": None}


def approved_plan(body: Optional[Ticket]) -> Optional[ApprovedPlan]:
    """The plan in force under a ticket: open, in execute or deliver, with an ApprovedPlan. None otherwise.

    Args:
        body: a ticket, or None.

    Returns:
        The ticket's plan when it is in force, else None.
    """
    if not body or body.get("state") != OPEN or body.get("phase") not in PHASES:
        return None
    plan = body.get("plan")
    return plan if isinstance(plan, dict) and plan.get("type") == APPROVED_PLAN else None


def in_force(port: PlanStore, sid: str) -> Optional[tuple[Ticket, ApprovedPlan]]:
    """The one reader of the plan in force: the session's ticket and its approved plan with its grants.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        sid: the Claude Code session id ("" for none).

    Returns:
        (ticket, plan with its grants), or None when the session has no approved plan.
    """
    ticket = port.ticket(sid) if sid else None
    plan = approved_plan(ticket)
    return None if plan is None else (ticket, {**plan, "grants": port.grants(plan)})


def latest(con: sqlite3.Connection, sid: str) -> Optional[Ticket]:
    """The newest ticket of a session.

    Args:
        con: an open connection to the ledger.
        sid: the Claude Code session id.

    Returns:
        The ticket of the highest seq, or None when the session has none.
    """
    row = con.execute("SELECT body FROM pl_tickets WHERE sid = ? ORDER BY seq DESC LIMIT 1", (sid,)).fetchone()
    return json.loads(row[0]) if row else None


def open_with_draft(con: sqlite3.Connection, draft: str) -> Optional[Ticket]:
    """The open ticket whose plan is the desk plan draft (pd-...), whatever its session.

    Args:
        con: an open connection to the ledger.
        draft: the desk id (pd-...).

    Returns:
        The newest open ticket of that draft with a plan in force, or None.
    """
    for (body,) in con.execute("SELECT body FROM pl_tickets WHERE state = ? ORDER BY seq DESC", (OPEN,)).fetchall():
        ticket = json.loads(body)
        if ticket.get("draft") == draft and approved_plan(ticket):
            return ticket
    return None


def save(con: sqlite3.Connection, body: Ticket) -> Ticket:
    """Write the ticket: its own row changes in place; a new ticket takes the next seq of its session.

    Args:
        con: the connection of the transaction.
        body: the ticket; its id, sid and state are needed.

    Returns:
        The same body.
    """
    row = con.execute("SELECT seq FROM pl_tickets WHERE id = ?", (body["id"],)).fetchone()
    seq = row[0] if row else 1 + (con.execute("SELECT MAX(seq) FROM pl_tickets WHERE sid = ?", (body["sid"],))
                                  .fetchone()[0] or 0)
    con.execute("INSERT OR REPLACE INTO pl_tickets (id, sid, seq, state, units, body, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (body["id"], body["sid"], seq, body["state"], json.dumps(body.get("units", [])),
                 json.dumps(body, ensure_ascii=False), now()))
    return body


def open_plan(con: sqlite3.Connection, sid: str, plan: dict[str, Any]) -> Ticket:
    """The ticket of a plan the user just approved in session sid:
    - an open ticket with no plan is reused;
    - an open ticket of the same desk plan (a revision) keeps its id, rootId and work, and takes the new plan;
    - an open ticket of another plan closes superseded, and the new ticket carries its done steps and commits;
    - else a new ticket. The ticket is in execute. A child's role and its questions (CARRIED) go with it to any new
      ticket: the session stays the child its brief made it.

    Args:
        con: the connection of the transaction.
        sid: the Claude Code session id.
        plan: the plan's items with id (plan number), plan_id, rev, base and sha; type is set here.

    Returns:
        The ticket saved, in execute, holding the plan.
    """
    plan = {**plan, "type": APPROVED_PLAN}
    old = latest(con, sid)
    kept = {k: old[k] for k in CARRIED if old and k in old}  # a child stays a child on any new ticket
    if old and old["state"] == OPEN and old.get("plan") and old.get("draft") == plan["plan_id"]:
        ticket = {**old, "plan": plan, "phase": EXECUTE if old["phase"] == PREPARE else old["phase"]}
        return save(con, ticket)
    if old and old["state"] == OPEN and old.get("plan"):
        save(con, {**old, "state": CLOSED, "closeReason": SUPERSEDED})
        ticket = {**blank(sid), "doneSteps": old["doneSteps"], "priorCommits": old["priorCommits"] + old["commits"],
                  "spentPlan": old["plan"]["id"]}
    elif old and old["state"] == OPEN:
        ticket = old
    else:
        ticket = blank(sid)
    return save(con, {**ticket, **kept, "phase": EXECUTE, "plan": plan, "draft": plan["plan_id"],
                      "rootId": plan["id"], "freshApproval": True})


def deliver(con: sqlite3.Connection, ticket: Ticket, sha: str) -> Ticket:
    """The plan's change is committed: its last step is done. A home plan closes delivered at once (no form).

    Args:
        con: the connection of the transaction.
        ticket: the open ticket of the plan.
        sha: the commit that delivers it.

    Returns:
        The ticket saved: closed delivered, with the commit added.
    """
    done = {**ticket, "commits": ticket["commits"] + [sha], "phase": DELIVER}
    return save(con, {**done, "state": CLOSED, "closeReason": DELIVERED})


def close(con: sqlite3.Connection, ticket: Ticket, reason: str) -> Ticket:
    """Close a ticket.

    Args:
        con: the connection of the transaction.
        ticket: the ticket.
        reason: its closeReason (delivered, abandoned, superseded).

    Returns:
        The ticket saved, closed.
    """
    return save(con, {**ticket, "state": CLOSED, "closeReason": reason})


def steps_of(plan: PlanItems) -> list[Step]:
    """The plan's steps; a plan with none is one step of all its files and tests.

    Args:
        plan: a plan's items (an ApprovedPlan too).

    Returns:
        Its steps, or [one step of its commit, files and tests, with no points].
    """
    return plan.get("steps") or [{"commit": plan.get("commit") or "", "files": plan.get("files", []),
                                  "tests": plan.get("tests", []), "points": []}]


def move(ticket: Ticket) -> Ticket:
    """After the current step's commit or skip: the next step opens in execute; after the last, the ticket is in
    deliver.

    Args:
        ticket: a ticket with a plan.

    Returns:
        A new body (not saved): step + 1 in execute, or the same step in deliver.
    """
    last = ticket["step"] >= len(steps_of(ticket["plan"])) - 1
    return {**ticket, "phase": DELIVER} if last else {**ticket, "step": ticket["step"] + 1, "phase": EXECUTE}


def back_to_execute(ticket: Ticket) -> Ticket:
    """A write to a plan file while the ticket is in deliver: the change goes back to execute, for a fix commit.

    Args:
        ticket: a ticket in deliver.

    Returns:
        A new body (not saved) in execute, backs counted up and backTold False.
    """
    return {**ticket, "phase": EXECUTE, "backs": ticket.get("backs", 0) + 1, "backTold": False}
