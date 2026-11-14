"""Tickets: one JSON body per ticket in pl_tickets (id, sid, seq, state, units, body, at); the newest seq of a session is
its ticket. A ticket runs a plan from its approval to its close:
  state      open | closed;  closeReason: delivered | abandoned | superseded
  phase      prepare (no plan) | execute | deliver
  plan       the ApprovedPlan {type, id (the plan number), plan_id (the desk id), rev, base, title, files, tests, root}
  draft, rootId   the desk id and the first plan number, kept across revisions
  step, commits, skips, doneSteps, priorCommits, spentPlan   the work done, and what a superseded ticket carried over
approved_plan(body) is the one rule for "a plan is in force". The functions take the open sqlite connection of a write
(or of a read), so a ticket changes in the same transaction as the rows around it."""
import itertools
import json
import time

from harness.utils.contracts import DELIVER, EXECUTE, PHASES, PREPARE

OPEN, CLOSED = "open", "closed"
DELIVERED, ABANDONED, SUPERSEDED = "delivered", "abandoned", "superseded"
APPROVED_PLAN = "ApprovedPlan"
DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
_count = itertools.count()


def now():
    return int(time.time() * 1000)


def base36(n):
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = DIGITS[r] + out
        if not n:
            return out


def new_id():
    return f"t-{base36(now())}-{next(_count)}"


def blank(sid):
    return {"id": new_id(), "sid": sid, "state": OPEN, "phase": PREPARE, "plan": None, "draft": None, "rootId": None,
            "step": 0, "commits": [], "skips": 0, "doneSteps": [], "priorCommits": [], "closeReason": None}


def approved_plan(body):
    """The plan in force under a ticket: open, in execute or deliver, with an ApprovedPlan. None otherwise."""
    if not body or body.get("state") != OPEN or body.get("phase") not in PHASES:
        return None
    plan = body.get("plan")
    return plan if isinstance(plan, dict) and plan.get("type") == APPROVED_PLAN else None


def latest(con, sid):
    row = con.execute("SELECT body FROM pl_tickets WHERE sid = ? ORDER BY seq DESC LIMIT 1", (sid,)).fetchone()
    return json.loads(row[0]) if row else None


def open_with_draft(con, draft):
    """The open ticket whose plan is the desk plan draft (pd-...), whatever its session."""
    for (body,) in con.execute("SELECT body FROM pl_tickets WHERE state = ? ORDER BY seq DESC", (OPEN,)).fetchall():
        ticket = json.loads(body)
        if ticket.get("draft") == draft and approved_plan(ticket):
            return ticket
    return None


def save(con, body):
    """Write the ticket: its own row changes in place; a new ticket takes the next seq of its session."""
    row = con.execute("SELECT seq FROM pl_tickets WHERE id = ?", (body["id"],)).fetchone()
    seq = row[0] if row else 1 + (con.execute("SELECT MAX(seq) FROM pl_tickets WHERE sid = ?", (body["sid"],))
                                  .fetchone()[0] or 0)
    con.execute("INSERT OR REPLACE INTO pl_tickets (id, sid, seq, state, units, body, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (body["id"], body["sid"], seq, body["state"], json.dumps(body.get("units", [])),
                 json.dumps(body, ensure_ascii=False), now()))
    return body


def open_plan(con, sid, plan):
    """The ticket of a plan the user just approved in session sid:
    - an open ticket with no plan is reused;
    - an open ticket of the same desk plan (a revision) keeps its id, rootId and work, and takes the new plan;
    - an open ticket of another plan closes superseded, and the new ticket carries its done steps and commits;
    - else a new ticket. The ticket is in execute."""
    plan = {**plan, "type": APPROVED_PLAN}
    old = latest(con, sid)
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
    return save(con, {**ticket, "phase": EXECUTE, "plan": plan, "draft": plan["plan_id"], "rootId": plan["id"],
                      "freshApproval": True})


def deliver(con, ticket, sha):
    """The plan's change is committed: its last step is done. A home plan closes delivered at once (no form)."""
    done = {**ticket, "commits": ticket["commits"] + [sha], "phase": DELIVER}
    return save(con, {**done, "state": CLOSED, "closeReason": DELIVERED})


def close(con, ticket, reason):
    return save(con, {**ticket, "state": CLOSED, "closeReason": reason})
