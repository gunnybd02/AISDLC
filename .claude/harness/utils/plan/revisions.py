"""Revisions of desk plans (pl_plan_revs) and what they went through (pl_plan_events, pl_plan_feedback). A revision
keeps the plan's items, the session that presented it, why each item changed, and the sha of its rendered block. The
state of a desk plan is its newest event: waiting, approved, executing, delivered, dropped."""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import TYPE_CHECKING, Any, Optional

from harness.utils.contracts import YES, now
from harness.utils.plan.render import block, sha
from harness.utils.shapes import PlanItems, Revision

if TYPE_CHECKING:
    from harness.utils.ledger.recorder import Recorder


def record(con: sqlite3.Connection, rec: Recorder, plan_id: str, sid: str, items: PlanItems,
           why: Optional[dict[str, Any]] = None) -> int:
    """Keep a new revision of plan_id; its number.

    Args:
        con: the connection of the transaction.
        rec: the recorder of the transaction.
        plan_id: the desk id (pd-...).
        sid: the Claude Code session that presents it.
        items: the plan's items, as desk.normalize keeps them.
        why: {item: why it changed} of a revision; None or {} for none.

    Returns:
        The new revision's number (1 for the first).
    """
    rev = 1 + (con.execute("SELECT MAX(rev) FROM pl_plan_revs WHERE plan_id = ?", (plan_id,)).fetchone()[0] or 0)
    rec.insert(con, "pl_plan_revs", {"plan_id": plan_id, "rev": rev, "sid": sid, "at": now(),
                                     "items": json.dumps(items, sort_keys=True, ensure_ascii=False),
                                     "why": json.dumps(why or {}, ensure_ascii=False),
                                     "sha": sha(block(items))})
    return rev


def newest(con: sqlite3.Connection, plan_id: str) -> Optional[Revision]:
    """{plan_id, rev, sid, items, sha, at, revisions, event} of the plan's newest revision, or None.

    Args:
        con: an open connection to the ledger.
        plan_id: the desk id (pd-...).

    Returns:
        The newest revision with its newest event and event_rev (Revision, without question); None when none.
    """
    row = con.execute("SELECT rev, sid, items, sha, at FROM pl_plan_revs WHERE plan_id = ? ORDER BY rev DESC LIMIT 1",
                      (plan_id,)).fetchone()
    if row is None:
        return None
    last = con.execute("SELECT event, rev FROM pl_plan_events WHERE plan_id = ? ORDER BY n DESC LIMIT 1",
                       (plan_id,)).fetchone()
    count = con.execute("SELECT COUNT(*) FROM pl_plan_revs WHERE plan_id = ?", (plan_id,)).fetchone()[0]
    return {"plan_id": plan_id, "rev": row[0], "sid": row[1], "items": json.loads(row[2]), "sha": row[3], "at": row[4],
            "revisions": count, "event": last[0] if last else None, "event_rev": last[1] if last else None}


def waiting(con: sqlite3.Connection) -> list[Revision]:
    """The newest revision of every desk plan whose newest event is 'waiting' for that very revision.

    Args:
        con: an open connection to the ledger.

    Returns:
        The waiting revisions (Revision, without question), in the order their plans were first kept.
    """
    ids = [r[0] for r in con.execute("SELECT DISTINCT plan_id FROM pl_plan_revs ORDER BY at").fetchall()]
    found = [newest(con, i) for i in ids]
    return [f for f in found if f and f["event"] == "waiting" and f["event_rev"] == f["rev"]]


def feedback(con: sqlite3.Connection, plan_id: str, rev: int, sid: str, text: str, item: str = "form") -> None:
    """Keep the user's words on a revision in pl_plan_feedback.

    Args:
        con: the connection of the transaction.
        plan_id: the desk id (pd-...).
        rev: the revision the words are on.
        sid: the Claude Code session id.
        text: the words.
        item: what they are about ("form": the answer to the form question).
    """
    con.execute("INSERT INTO pl_plan_feedback (uid, plan_id, rev, item, text, sid, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, plan_id, rev, item, text, sid, now()))


def unread(con: sqlite3.Connection, plan_id: str, since: int) -> list[str]:
    """The feedback on the plan given after its newest revision was kept; the approval word itself is no feedback to
    answer.

    Args:
        con: an open connection to the ledger.
        plan_id: the desk id (pd-...).
        since: the time in ms the newest revision was kept.

    Returns:
        The texts, oldest first.
    """
    return [r[0] for r in con.execute("SELECT text FROM pl_plan_feedback WHERE plan_id = ? AND at >= ? AND text != ? "
                                      "ORDER BY at", (plan_id, since, YES)).fetchall()]
