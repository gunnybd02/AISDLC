"""PlanOpening (docs 04, section 3): the user approved a waiting revision in the form. One transaction writes, in order:
1. rec_plans: the plan number (a chained row); the same sid, sha and approval as the open ticket's plan is reused;
2. pl_behaviors: one 'add' row per behaviour with a test (status active); one without a test lives in the plan only;
3. pl_tickets: the ticket (utils/plan/tickets.py) in phase execute;
4. pl_approval: open, approved {sha, plan, at}, nothing pending;
5. pl_plan_events: approved, then executing (each skipped when it is already the last event);
6. pl_logs gate-open and form, and the user's word in pl_plan_feedback."""
import hashlib
import json
import time
import uuid

from harness.utils.contracts import YES
from harness.utils.plan import tickets


def now():
    return int(time.time() * 1000)


def event(con, rec, plan_id, name, rev, ref=None, sid=""):
    last = con.execute("SELECT event FROM pl_plan_events WHERE plan_id = ? ORDER BY n DESC LIMIT 1",
                       (plan_id,)).fetchone()
    if last and last[0] == name and name != "waiting":
        return
    n = 1 + (con.execute("SELECT MAX(n) FROM pl_plan_events WHERE plan_id = ?", (plan_id,)).fetchone()[0] or 0)
    rec.insert(con, "pl_plan_events", {"plan_id": plan_id, "n": n, "sid": sid, "event": name, "rev": rev, "ref": ref,
                                       "at": now()})


def log(con, sid, what, **detail):
    con.execute("INSERT INTO pl_logs (uid, body, at) VALUES (?, ?, ?)",
                (uuid.uuid4().hex, json.dumps({"what": what, "sid": sid, **detail}, ensure_ascii=False), now()))


def approval(con, sid, body):
    con.execute("INSERT OR REPLACE INTO pl_approval (sid, body, at) VALUES (?, ?, ?)",
                (sid, json.dumps(body, ensure_ascii=False), now()))


def open_plan(con, rec, sid, waiting, base):
    """Open the approved revision waiting {plan_id, rev, items, sha} in session sid; its plan number."""
    plan_id, rev, items, sha = waiting["plan_id"], waiting["rev"], waiting["items"], waiting["sha"]
    scope = {"plan_id": plan_id, "rev": rev, "base": base, **items}
    held = tickets.approved_plan(tickets.latest(con, sid))
    if held and held.get("sha") == sha and held.get("plan_id") == plan_id:
        rid = held["id"]
    else:
        rid = rec.insert(con, "rec_plans", {
            "sid": sid, "sha": hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()[:8],
            "reason": "form", "scope": json.dumps(scope, ensure_ascii=False), "services": json.dumps(items.get("services", [])),
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
    approval(con, sid, {"open": True, "approved": {"sha": sha, "plan": rid, "at": now()}, "pending": None,
                        "tool": None})
    event(con, rec, plan_id, "approved", rev, rid, sid)
    event(con, rec, plan_id, "executing", rev, rid, sid)
    log(con, sid, "gate-open", plan=rid, draft=plan_id, rev=rev)
    log(con, sid, "form", plan=rid, answer=YES)
    con.execute("INSERT INTO pl_plan_feedback (uid, plan_id, rev, item, text, sid, at) VALUES (?, ?, ?, 'form', ?, ?, ?)",
                (uuid.uuid4().hex, plan_id, rev, YES, sid, now()))
    return rid
