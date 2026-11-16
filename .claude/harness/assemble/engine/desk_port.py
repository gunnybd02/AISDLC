"""The desk plans of LedgerPort (ports.py), before a plan is in force:
- present: a revision of a desk plan (its items, utils/plan/desk.py, and its root), waiting (pl_plan_revs,
  utils/plan/revisions.py, a 'waiting' event); drop: a waiting plan no longer waits ('dropped');
- approve: the user's "Duy\u1ec7t" in the form to that revision's question (a chained rec_plans row, an 'approved' event);
- feedback, unread: the user's words on a revision; prompt: the user's prompt, and the plan a bare agreement word
  would wrongly approve."""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from harness.assemble.engine.ledger_core import LedgerCore
from harness.utils.git.facts import head, top
from harness.utils.plan import opening, render, request, revisions
from harness.utils.plan.desk import new_id
from harness.utils.ledger.recorder import Recorder
from harness.utils.shapes import PlanItems, Revision


def question(items: PlanItems, plan_id: str, rev: int) -> str:
    """The form question of a revision (utils/plan/render.py); the block above it shows what the user approves.

    Args:
        items: the plan's items (PlanItems).
        plan_id: the desk id (pd-...).
        rev: the revision number.

    Returns:
        The question whose answer "Duy\u1ec7t" approves exactly that revision.
    """
    return render.question(items, plan_id, rev)


class DeskPort(LedgerCore):
    """The ledger's desk plans: revisions presented, dropped, approved, and the user's words on them."""

    def present(self, items: PlanItems, plan_id: Optional[str] = None, sid: str = "",
                why: Optional[dict] = None) -> tuple[str, int, str]:
        """Keep a revision of a desk plan (a new one without plan_id); give (plan id, revision, the form question).

        Args:
            items: the plan's items, cleaned and with their root (PlanItems).
            plan_id: the desk id of the plan revised, or None for a new plan.
            sid: the session that presents it ("" when none); its approval row then shows it pending.
            why: {item: why it changed} for a revision, kept with it; None for none.

        Returns:
            (plan id, revision number, the form question that approves it).
        """
        plan_id = plan_id or new_id()

        def change(con: sqlite3.Connection, rec: Recorder) -> int:
            rev = revisions.record(con, rec, plan_id, sid, items, why)
            self.event(con, rec, plan_id, "waiting", rev, sid=sid)
            if sid:
                held = (json.loads(r[0]) for r in con.execute("SELECT body FROM pl_approval WHERE sid = ?", (sid,)))
                opening.approval(con, sid, {**next(held, {"open": False}), "pending": render.block(items, plan_id, rev),
                                            "pendingAge": 0, "tool": {"planId": plan_id, "rev": rev,
                                                                      "sha": revisions.newest(con, plan_id)["sha"]}})
            return rev

        rev = self.write(change)
        return plan_id, rev, question(items, plan_id, rev)

    def revision(self, plan_id: str) -> Optional[Revision]:
        """The newest revision of a desk plan and its state (utils/plan/revisions.newest), or None.

        Args:
            plan_id: the desk id (pd-...).

        Returns:
            The newest Revision with its newest event, or None when the plan is unknown or there is no ledger.
        """
        return self.read(lambda con: revisions.newest(con, plan_id))

    def drop(self, plan_id: str, rev: int, sid: str) -> None:
        """Drop a waiting revision: a 'dropped' event, and the session's approval row no longer shows it pending.

        Args:
            plan_id: the desk id (pd-...).
            rev: the revision dropped.
            sid: the session that drops it.
        """
        def change(con: sqlite3.Connection, rec: Recorder) -> None:
            self.event(con, rec, plan_id, "dropped", rev, sid=sid)
            held = [json.loads(r[0]) for r in con.execute("SELECT body FROM pl_approval WHERE sid = ?", (sid,))]
            if held:
                opening.approval(con, sid, {**held[0], "pending": None, "tool": None})
        self.write(change)

    def feedback(self, plan_id: str, rev: int, sid: str, text: str) -> None:
        """Keep the user's words on a revision (pl_plan_feedback).

        Args:
            plan_id: the desk id (pd-...).
            rev: the revision they are about.
            sid: the session they were given in.
            text: the user's words.
        """
        self.write(lambda con, rec: revisions.feedback(con, plan_id, rev, sid, text))

    def unread(self, plan_id: str, since: int) -> list[str]:
        """The feedback on the plan given since a time (utils/plan/revisions.unread); the approval word is none.

        Args:
            plan_id: the desk id (pd-...).
            since: the time in ms the newest revision was kept.

        Returns:
            The texts of the feedback, oldest first; [] with none or no ledger.
        """
        return self.read(lambda con: revisions.unread(con, plan_id, since)) or []

    def waiting(self) -> list[Revision]:
        """The newest revision of each desk plan that waits for its approval, with its question.

        Returns:
            Each waiting Revision with its question added.
        """
        return [{**w, "question": question(w["items"], w["plan_id"], w["rev"])}
                for w in self.read(revisions.waiting) or []]

    def approve(self, sid: str, waiting: Revision) -> int:
        """The user approved this waiting revision in the session sid: open it in one transaction
        (utils/plan/opening.py). base is the commit its repository stands on now, which a delivered commit must come
        from.

        Args:
            sid: the session the user approved it in.
            waiting: the waiting Revision approved (plan_id, rev, items with their root, sha).

        Returns:
            The plan number in rec_plans of the plan now in force.
        """
        repo = top(waiting["items"]["root"])
        base = head(repo) if repo else None
        return self.write(lambda con, rec: opening.open_plan(con, rec, sid, waiting, base))

    def prompt(self, sid: str, text: str) -> Optional[Revision]:
        """Keep the user's prompt; the plan a bare agreement word would wrongly approve, or None.

        Args:
            sid: the session the prompt was typed in.
            text: the prompt.

        Returns:
            The newest waiting Revision of the session (or of no session) when the prompt is a bare agreement word
            (ok, duy\u1ec7t...), which approves nothing; None otherwise.
        """
        self.write(lambda con, rec: request.record_prompt(con, sid, text))
        if request.bare_agreement(text):
            mine = [w for w in self.waiting() if w["sid"] in (sid, "")]
            return mine[-1] if mine else None
        return None
