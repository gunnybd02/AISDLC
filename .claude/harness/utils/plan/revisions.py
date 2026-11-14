"""Revisions of desk plans (pl_plan_revs) and what they went through (pl_plan_events, pl_plan_feedback). A revision
keeps the plan's items, the session that presented it, why each item changed, and the sha of its rendered block. The
state of a desk plan is its newest event: waiting, approved, executing, delivered, dropped."""
import json
import time
import uuid

from harness.utils.contracts import YES
from harness.utils.plan.render import block, sha


def now():
    return int(time.time() * 1000)


def record(con, rec, plan_id, sid, items, why=None):
    """Keep a new revision of plan_id; its number."""
    rev = 1 + (con.execute("SELECT MAX(rev) FROM pl_plan_revs WHERE plan_id = ?", (plan_id,)).fetchone()[0] or 0)
    rec.insert(con, "pl_plan_revs", {"plan_id": plan_id, "rev": rev, "sid": sid, "at": now(),
                                     "items": json.dumps(items, sort_keys=True, ensure_ascii=False),
                                     "why": json.dumps(why or {}, ensure_ascii=False),
                                     "sha": sha(block(items, plan_id, rev))})
    return rev


def newest(con, plan_id):
    """{plan_id, rev, sid, items, sha, at, revisions, event} of the plan's newest revision, or None."""
    row = con.execute("SELECT rev, sid, items, sha, at FROM pl_plan_revs WHERE plan_id = ? ORDER BY rev DESC LIMIT 1",
                      (plan_id,)).fetchone()
    if row is None:
        return None
    last = con.execute("SELECT event, rev FROM pl_plan_events WHERE plan_id = ? ORDER BY n DESC LIMIT 1",
                       (plan_id,)).fetchone()
    count = con.execute("SELECT COUNT(*) FROM pl_plan_revs WHERE plan_id = ?", (plan_id,)).fetchone()[0]
    return {"plan_id": plan_id, "rev": row[0], "sid": row[1], "items": json.loads(row[2]), "sha": row[3], "at": row[4],
            "revisions": count, "event": last[0] if last else None, "event_rev": last[1] if last else None}


def waiting(con):
    """The newest revision of every desk plan whose newest event is 'waiting' for that very revision."""
    ids = [r[0] for r in con.execute("SELECT DISTINCT plan_id FROM pl_plan_revs ORDER BY at").fetchall()]
    found = [newest(con, i) for i in ids]
    return [f for f in found if f and f["event"] == "waiting" and f["event_rev"] == f["rev"]]


def feedback(con, plan_id, rev, sid, text, item="form"):
    con.execute("INSERT INTO pl_plan_feedback (uid, plan_id, rev, item, text, sid, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, plan_id, rev, item, text, sid, now()))


def unread(con, plan_id, since):
    """The feedback on the plan given after its newest revision was kept; the approval word itself is no feedback to
    answer."""
    return [r[0] for r in con.execute("SELECT text FROM pl_plan_feedback WHERE plan_id = ? AND at >= ? AND text != ? "
                                      "ORDER BY at", (plan_id, since, YES)).fetchall()]
