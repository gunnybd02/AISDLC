"""PlanOpening (docs 04, section 3): the user approved a waiting revision in the form. One transaction writes, in order:
1. rec_plans: the plan number (a chained row); the same sid, sha and approval as the open ticket's plan is reused;
2. pl_behaviors: one 'add' row per behaviour with a test (status active); one without a test lives in the plan only;
3. pl_tickets: the ticket (utils/plan/tickets.py) in phase execute; a plan with children makes it delegated
   (utils/orchestra/crew.open_delegated: the grant, the crew, a pending story row per child), and the change and
   test paths of its cards join its files and tests;
4. pl_approval: open, approved {sha, plan, at}, nothing pending;
5. pl_plan_events: approved, then executing (each skipped when it is already the last event);
6. pl_logs gate-open and form, and the user's word in pl_plan_feedback. A child's card plan is opened by the grant of
   its parent plan instead (by): no form was asked, and the rows say grant."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from typing import TYPE_CHECKING, Any, Optional

from harness.utils.contracts import YES
from harness.utils.orchestra import card, crew
from harness.utils.plan import tickets
from harness.utils.shapes import Revision

if TYPE_CHECKING:
    from harness.utils.ledger.recorder import Recorder


def now() -> int:
    """The time now in ms.

    Returns:
        Milliseconds since the epoch.
    """
    return int(time.time() * 1000)


def event(con: sqlite3.Connection, rec: Recorder, plan_id: str, name: str, rev: int, ref: Optional[int] = None,
          sid: str = "") -> None:
    """Keep one event of a desk plan in pl_plan_events, unless it is already the plan's last (waiting is always kept).

    Args:
        con: the connection of the transaction.
        rec: the recorder of the transaction.
        plan_id: the desk id (pd-...).
        name: the event (waiting, approved, executing, delivered, dropped).
        rev: the revision it is for.
        ref: the plan number in rec_plans, or None.
        sid: the Claude Code session id.
    """
    last = con.execute("SELECT event FROM pl_plan_events WHERE plan_id = ? ORDER BY n DESC LIMIT 1",
                       (plan_id,)).fetchone()
    if last and last[0] == name and name != "waiting":
        return
    n = 1 + (con.execute("SELECT MAX(n) FROM pl_plan_events WHERE plan_id = ?", (plan_id,)).fetchone()[0] or 0)
    rec.insert(con, "pl_plan_events", {"plan_id": plan_id, "n": n, "sid": sid, "event": name, "rev": rev, "ref": ref,
                                       "at": now()})


def log(con: sqlite3.Connection, sid: str, what: str, **detail: Any) -> None:
    """Keep one row of pl_logs: {what, sid, **detail} as JSON.

    Args:
        con: the connection of the transaction.
        sid: the Claude Code session id.
        what: what happened (gate-open, form...).
        **detail: more keys of the row's body (plan, draft, rev, answer...).
    """
    con.execute("INSERT INTO pl_logs (uid, body, at) VALUES (?, ?, ?)",
                (uuid.uuid4().hex, json.dumps({"what": what, "sid": sid, **detail}, ensure_ascii=False), now()))


def approval(con: sqlite3.Connection, sid: str, body: dict[str, Any]) -> None:
    """Keep the session's approval state in pl_approval (one row per session, replaced).

    Args:
        con: the connection of the transaction.
        sid: the Claude Code session id.
        body: {open, approved: {sha, plan, at}, pending, tool}, kept as JSON.
    """
    con.execute("INSERT OR REPLACE INTO pl_approval (sid, body, at) VALUES (?, ?, ?)",
                (sid, json.dumps(body, ensure_ascii=False), now()))


def open_plan(con: sqlite3.Connection, rec: Recorder, sid: str, waiting: Revision, base: Optional[str],
              by: str = "") -> int:
    """Open the approved revision waiting {plan_id, rev, items, sha} in session sid; its plan number.

    Args:
        con: the connection of the transaction.
        rec: the recorder of the transaction.
        sid: the Claude Code session id the user approved it in.
        waiting: the approved revision.
        base: the commit the plan's repository stands on now, or None.
        by: "" for the user's answer in the form; else what approved it instead, for a child's card plan "grant of
            plan <n> (<parent session>)": rec_plans says reason grant, the logs and feedback say grant, not form.

    Returns:
        The plan number in rec_plans (the open ticket's, when it holds the same revision).
    """
    plan_id, rev, sha = waiting["plan_id"], waiting["rev"], waiting["sha"]
    items = card.with_card_files(waiting["items"])
    scope = {"plan_id": plan_id, "rev": rev, "base": base, **items}
    held = tickets.approved_plan(tickets.latest(con, sid))
    if held and held.get("sha") == sha and held.get("plan_id") == plan_id:
        rid = held["id"]
    else:
        rid = rec.insert(con, "rec_plans", {
            "sid": sid, "sha": hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()[:8],
            "reason": "grant" if by else "form", "scope": json.dumps(scope, ensure_ascii=False), "services": json.dumps(items.get("services", [])),
            "status": "approved", "at": now(), "uid": uuid.uuid4().hex})
    for b in items.get("behaviors", []):
        if b.get("test"):
            entry = {"what": b.get("what"), "how": b.get("how"), "why": b.get("why"), "tests": [b["test"]],
                     "status": "active", "plan": rid, "step": b.get("step")}
            rec.insert(con, "pl_behaviors", {"uid": uuid.uuid4().hex, "sid": sid, "plan_id": rid,
                                             "repo": items.get("root", ""), "op": "add", "id": b["id"],
                                             "entry": json.dumps(entry, ensure_ascii=False), "at": now()})
    plan = {"id": rid, "sha": sha, **scope, **({"commit": ""} if items.get("steps") else {})}
    tickets.open_plan(con, sid, plan)
    crew.open_delegated(con, sid)
    approval(con, sid, {"open": True, "approved": {"sha": sha, "plan": rid, "at": now()}, "pending": None,
                        "tool": None})
    event(con, rec, plan_id, "approved", rev, rid, sid)
    event(con, rec, plan_id, "executing", rev, rid, sid)
    log(con, sid, "gate-open", plan=rid, draft=plan_id, rev=rev)
    if by:
        log(con, sid, "grant", plan=rid, by=by)
    else:
        log(con, sid, "form", plan=rid, answer=YES)
    con.execute("INSERT INTO pl_plan_feedback (uid, plan_id, rev, item, text, sid, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, plan_id, rev, "grant" if by else "form", by or YES, sid, now()))
    return rid
