"""The tickets of LedgerPort (ports.py), once a plan is in force: the commits of its steps, a step given up, the plan
closed, delivered or ended, and a ticket sent back from deliver to execute (utils/plan/tickets.py). A ticket is the one
body that changes, in place; the audit rows are never changed after they are written."""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Optional

from harness.assemble.engine.ledger_core import LedgerCore, now
from harness.utils.plan import opening, tickets
from harness.utils.ledger.recorder import Recorder
from harness.utils.shapes import ApprovedPlan, Revision, Ticket


def home_plan(plan: ApprovedPlan) -> bool:
    """A plan of the home only (services none or agent-code): it closes itself after its last step; a plan of a unit
    stays in deliver for its push and merge request.

    Args:
        plan: the plan in force (ApprovedPlan).

    Returns:
        True when the plan touches no unit.
    """
    return set(plan.get("services") or ["agent-code"]) <= {"none", "agent-code"}


def closure(con: sqlite3.Connection, sid: str, ticket: Ticket, choice: str, facts: list[str]) -> None:
    """Keep the closing of a plan's ticket (pl_plan_closures): the choice, the facts the ledger held then, and what
    the ticket declares that the ledger does not show. One row per close, never changed.

    Args:
        con: the connection of the transaction.
        sid: the session that closes.
        ticket: the ticket closed, with its plan and commits.
        choice: delivered or abandoned.
        facts: the lines of facts shown at the close ("Summary: ..." is the summary).
    """
    plan = ticket.get("plan") or {}
    commits = list(ticket.get("commits", []))
    missing = [sha for sha in commits
               if not con.execute("SELECT 1 FROM rec_commits WHERE commit_sha = ?", (sha,)).fetchone()]
    summary = next((line[len("Summary: "):] for line in facts if line.startswith("Summary: ")), "")
    con.execute("INSERT INTO pl_plan_closures (uid, sid, plan_id, ticket, plan_no, choice, summary, facts, mismatches, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, sid, plan.get("plan_id", ""), ticket.get("id", ""), plan.get("id") or 0, choice,
                 summary, json.dumps({"lines": list(facts), "commits": commits}, ensure_ascii=False),
                 json.dumps([f"commit {sha[:12]}: declared by the ticket, not in the ledger" for sha in missing]), now()))


class TicketPort(LedgerCore):
    """The ledger's tickets: each moves its plan from its first step to its close, one transaction a move."""

    def note_commit(self, sid: str, plan: ApprovedPlan, repo: str, sha: str) -> None:
        """git.commit made a commit of the plan: keep it; the ticket notes it, and step_done adopts it (no move).

        Args:
            sid: the session whose ticket notes it.
            plan: the plan in force (ApprovedPlan).
            repo: the repository the commit is in.
            sha: the commit.
        """
        def change(con: sqlite3.Connection, rec: Recorder) -> None:
            rec.insert(con, "rec_commits", {"plan_id": plan["id"], "service": repo, "commit_sha": sha, "at": now(),
                                            "uid": uuid.uuid4().hex})
            fresh = tickets.latest(con, sid)
            tickets.save(con, {**fresh, "noted": fresh.get("noted", []) + [sha]})
        self.write(change)

    def step_commit(self, sid: str, ticket: Ticket, plan: ApprovedPlan, repo: str, sha: Optional[str],
                    fixing: bool) -> Ticket:
        """The step's commit is made (sha), or the commits git.commit noted are adopted (sha None): keep it; the ticket
        moves on (after the last step: deliver; a home plan then closes delivered with no form, a unit plan stays for
        push and merge request). A fix keeps the ticket in deliver. One transaction; the ticket after.

        Args:
            sid: the session whose ticket moves (it is read afresh inside the transaction).
            ticket: the ticket as the caller saw it (Ticket).
            plan: the plan in force (ApprovedPlan).
            repo: the repository of the commit.
            sha: the step's commit, or None to adopt the noted ones.
            fixing: whether this is a fix in deliver (the ticket stays in deliver).

        Returns:
            The ticket after the move.
        """
        def change(con: sqlite3.Connection, rec: Recorder) -> Ticket:
            fresh = tickets.latest(con, sid)
            shas = [sha] if sha else fresh.get("noted", [])
            if sha:
                rec.insert(con, "rec_commits", {"plan_id": plan["id"], "service": repo, "commit_sha": sha, "at": now(),
                                                "uid": uuid.uuid4().hex})
            step = str(fresh["step"])
            done = {**fresh, "commits": fresh["commits"] + shas, "noted": [],
                    "stepCommits": {**fresh.get("stepCommits", {}), step: fresh.get("stepCommits", {}).get(step, []) + shas}}
            done = {**done, "phase": "deliver"} if fixing else tickets.move(done)
            if not fixing and done["phase"] == "deliver" and not plan.get("children") and home_plan(plan) \
                    and not fresh.get("child"):  # a child's card plan waits in deliver for its handback
                done = {**done, "state": tickets.CLOSED, "closeReason": tickets.DELIVERED}
                self.event(con, rec, plan["plan_id"], "delivered", plan["rev"], plan["id"], sid)
                closure(con, sid, done, tickets.DELIVERED, ["Closed by its last step, with no form."])
            return tickets.save(con, done)
        return self.write(change)

    def step_skip(self, sid: str, ticket: Ticket, plan: ApprovedPlan, ids: list[str], why: str) -> Ticket:
        """Give the current step up: a skip row for each of its behaviours, and the ticket moves on.

        Args:
            sid: the session whose ticket moves.
            ticket: the ticket as the caller saw it (Ticket).
            plan: the plan in force (ApprovedPlan).
            ids: the ids of the step's behaviours skipped.
            why: the reason given.

        Returns:
            The ticket after the move.
        """
        def change(con: sqlite3.Connection, rec: Recorder) -> Ticket:
            for bid in ids:
                rec.insert(con, "pl_behaviors", {"uid": uuid.uuid4().hex, "sid": sid, "plan_id": plan["id"],
                                                 "repo": plan["root"], "op": "skip", "id": bid,
                                                 "entry": json.dumps({"why": why}, ensure_ascii=False), "at": now()})
            fresh = tickets.latest(con, sid)
            return tickets.save(con, tickets.move({**fresh, "skips": fresh.get("skips", 0) + 1}))
        return self.write(change)

    def close_plan(self, sid: str, ticket: Ticket, reason: str, facts: list[str]) -> None:
        """The user closed the ticket's plan in the close form (delivered or abandoned): one transaction closes the
        ticket, ends the approval, writes the event (delivered, dropped) and keeps the facts the user saw.

        Args:
            sid: the session whose ticket closes (read afresh inside the transaction).
            ticket: the ticket as the caller saw it (Ticket).
            reason: delivered or abandoned.
            facts: the lines of facts the close form showed (utils/plan/closing.py), kept in pl_logs.
        """
        def change(con: sqlite3.Connection, rec: Recorder) -> None:
            fresh = tickets.latest(con, sid)
            tickets.close(con, fresh, reason)
            held = [json.loads(r[0]) for r in con.execute("SELECT body FROM pl_approval WHERE sid = ?", (sid,))]
            opening.approval(con, sid, {**(held[0] if held else {}), "open": False})
            plan = fresh["plan"]
            self.event(con, rec, plan["plan_id"], "delivered" if reason == "delivered" else "dropped", plan["rev"],
                       plan["id"], sid)
            opening.log(con, sid, "closure", ticket=fresh["id"], plan=plan["id"], reason=reason, facts=facts)
            closure(con, sid, fresh, reason, facts)
        self.write(change)

    def holder(self, plan_id: str) -> Optional[Ticket]:
        """The newest ticket that holds the desk plan plan_id, open or closed, or None.

        Args:
            plan_id: the desk id (pd-...).

        Returns:
            The newest Ticket whose draft is plan_id, or None.
        """
        for r in self.rows("SELECT body FROM pl_tickets ORDER BY at DESC, seq DESC"):
            body = json.loads(r["body"])
            if body.get("draft") == plan_id:
                return body
        return None

    def end_plan(self, plan: Revision, how: str, abandon: bool = False) -> None:
        """plans_settle ends a desk plan: its event (delivered or dropped); with abandon, its open ticket closes.

        Args:
            plan: the open desk plan (utils/plan/life.py: a Revision with ref, the plan number it reached or None).
            how: the event written, delivered or dropped.
            abandon: whether its open ticket closes abandoned.
        """
        def change(con: sqlite3.Connection, rec: Recorder) -> None:
            if abandon:
                holder = next((json.loads(r[0]) for r in con.execute(
                    "SELECT body FROM pl_tickets WHERE state = 'open' ORDER BY seq DESC") if json.loads(r[0]).get("draft")
                               == plan["plan_id"]), None)
                if holder:
                    tickets.close(con, holder, tickets.ABANDONED)
            self.event(con, rec, plan["plan_id"], how, plan["rev"], plan.get("ref"), plan["sid"])
        self.write(change)

    def back(self, sid: str) -> None:
        """A write to a plan file while the ticket is in deliver sends it back to execute.

        Args:
            sid: the session whose ticket goes back (nothing changes when it is not in deliver).
        """
        def change(con: sqlite3.Connection, rec: Recorder) -> None:
            fresh = tickets.latest(con, sid)
            if fresh and tickets.approved_plan(fresh) and fresh["phase"] == "deliver":
                tickets.save(con, tickets.back_to_execute(fresh))
        self.write(change)

    def deliver(self, sid: str, plan: ApprovedPlan, repo: str, sha: str) -> None:
        """The plan's change is committed: keep the commit; its ticket closes delivered (a home plan needs no form).

        Args:
            sid: the session of the delivery (the event names the ticket's own session when it has one).
            plan: the plan delivered (ApprovedPlan).
            repo: the repository of the commit.
            sha: the commit that delivers it.
        """
        def change(con: sqlite3.Connection, rec: Recorder) -> None:
            rec.insert(con, "rec_commits", {"plan_id": plan["id"], "service": repo, "commit_sha": sha, "at": now(),
                                            "uid": uuid.uuid4().hex})
            ticket = tickets.open_with_draft(con, plan["plan_id"])
            if ticket:
                tickets.deliver(con, ticket, sha)
            self.event(con, rec, plan["plan_id"], "delivered", plan["rev"], plan["id"], ticket["sid"] if ticket else sid)
        self.write(change)
