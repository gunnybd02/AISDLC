"""The parts of the ledger port PlanStore (shapes.py; built as assemble/engine/ports.py LedgerPort), by what they give:
LedgerAccess (the file, plain reads and writes, the session, the home), PlanFacts (the plan in force and what is kept
of it), DeskStore (desk plans and their approval), TicketStore (the run of a plan). Name PlanStore in a hint, not a
part. Nothing here runs: these are types and their documentation only."""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol

if TYPE_CHECKING:
    from harness.utils.contracts import Event, Finding
    from harness.utils.shapes import (ApprovedPlan, Behaviour, Change, Grant, PlanItems, Receipt, Revision, Row, T,
                                      Ticket)


class LedgerAccess(Protocol):
    """The ledger itself: its file, one read query, one write transaction, and the session at work."""
    path: Path

    def rows(self, sql: str, args: tuple[Any, ...] | list[Any] = ()) -> list[Row]:
        """The rows of one read query; [] when there is no ledger yet.

        Args:
            sql: one SELECT with ? marks.
            args: the values of the marks.

        Returns:
            Each row as a dict by column name.
        """

    def write(self, change: Change[T]) -> T:
        """Run change(con, rec) in one transaction and give back what it returns.

        Args:
            change: change(con, rec) makes the writes; rec inserts rows, chained ones too.

        Returns:
            What change returns.
        """

    def read(self, look: Callable[[sqlite3.Connection], T]) -> Optional[T]:
        """look(con) on the ledger, or None when there is no ledger yet.

        Args:
            look: look(con) reads on an open connection.

        Returns:
            What look returns, or None with no ledger.
        """

    def touch_session(self, sid: str) -> None:
        """Mark the session as the one at work now.

        Args:
            sid: the Claude Code session id ("" changes nothing).
        """

    def session(self) -> str:
        """The session the hook saw last.

        Returns:
            The session id, or "" when none.
        """

    def protected(self, branch: str) -> bool:
        """Whether the branch is protected.

        Args:
            branch: the branch name (refs/heads/ may lead).

        Returns:
            True when a protected name or pattern matches it.
        """

    def is_home(self, repo: str) -> bool:
        """Whether repo is the repository that holds the harness.

        Args:
            repo: a folder.

        Returns:
            True when repo is in the home's git repository.
        """

    def committed(self, sha: str) -> bool:
        """Whether the ledger keeps the commit sha.

        Args:
            sha: the commit.

        Returns:
            True when some plan's commit is sha (rec_commits).
        """

    def decision(self, event: Event, plan: Optional[ApprovedPlan], finding: Finding, verdict: str) -> None:
        """Keep one finding of a hook call with the word Claude Code was given.

        Args:
            event: the hook call.
            plan: the plan in force in its session, or None.
            finding: the finding kept.
            verdict: the word Claude Code was given for the call.
        """


class PlanFacts(Protocol):
    """The plan in force in a session and what the ledger keeps of it."""

    def ticket(self, sid: str) -> Optional[Ticket]:
        """The newest ticket of the session, or None.

        Args:
            sid: the Claude Code session id.

        Returns:
            Its newest Ticket, open or closed, or None.
        """

    def approved(self, sid: str) -> Optional[ApprovedPlan]:
        """The plan in force in the session with its grants, or None.

        Args:
            sid: the Claude Code session id.

        Returns:
            The ApprovedPlan with its grants, or None.
        """

    def grants(self, plan: ApprovedPlan) -> list[Grant]:
        """The file grants of the plan, in the order given.

        Args:
            plan: the plan in force; its id and root are read.

        Returns:
            Each grant as (op, path from the plan's root); op is add or drop.
        """

    def approved_plan(self, plan_id: str) -> Optional[ApprovedPlan]:
        """The plan in force whose desk id is plan_id, whatever its session, or None.

        Args:
            plan_id: the desk id (pd-...).

        Returns:
            The ApprovedPlan (without its grants), or None when no open ticket holds it.
        """

    def registry(self, plan: ApprovedPlan) -> dict[str, Behaviour]:
        """The behaviour registry of the plan: {behaviour id: entry}.

        Args:
            plan: the plan in force; the rows of its first revision (rootId) count too.

        Returns:
            {behaviour id: Behaviour}.
        """

    def changed_files(self, plan: ApprovedPlan) -> list[str]:
        """The files of the plan's root that differ from HEAD.

        Args:
            plan: the plan in force.

        Returns:
            Their paths from the plan's root (those the plan allows).
        """

    def door(self, sid: str, plan: ApprovedPlan, grants: Sequence[tuple[str, str, str]] = (),
             behaviors: Sequence[tuple[str, str, dict[str, Any]]] = ()) -> None:
        """Keep the rows of one CLI door: file grants (op, path, why) and behaviour rows (op, id, entry).

        Args:
            sid: the Claude Code session id of the door.
            plan: the plan in force.
            grants: (op, absolute path, why) of each file grant; op add or drop.
            behaviors: (op, behaviour id, entry) of each behaviour row; op add, retire...
        """

    def keep_verify(self, plan: ApprovedPlan, receipt: Receipt) -> None:
        """Keep a verify receipt of the plan.

        Args:
            plan: the plan verified.
            receipt: the result of the run.
        """

    def green_receipt(self, plan: ApprovedPlan) -> Optional[Receipt]:
        """The newest passing receipt of the plan ({ok, files}), or None.

        Args:
            plan: the plan in force.

        Returns:
            {ok: 1, files: {path: blob id}}, or None when no verify of it passed.
        """

    def receipt(self, plan: ApprovedPlan) -> Optional[Receipt]:
        """The newest receipt of the plan ({ok, files}), or None.

        Args:
            plan: the plan in force.

        Returns:
            {ok, files: {path: blob id}}, green or not, or None when it was never verified.
        """


class DeskStore(Protocol):
    """The desk plans: their revisions, the user's words on them, and the approval that opens one."""

    def present(self, items: PlanItems, plan_id: Optional[str] = None, sid: str = "",
                why: Optional[dict[str, Any]] = None) -> tuple[str, int, str]:
        """Keep a revision of a desk plan: (plan id, revision, the form question).

        Args:
            items: the plan's items, cleaned and with their root.
            plan_id: the desk id of the plan revised, or None for a new plan.
            sid: the Claude Code session that presents it ("" when none).
            why: {item: why it changed} of a revision, or None.

        Returns:
            (the desk id, the revision number, the form question that approves it).
        """

    def revision(self, plan_id: str) -> Optional[Revision]:
        """The newest revision of a desk plan, or None.

        Args:
            plan_id: the desk id (pd-...).

        Returns:
            The newest Revision with its newest event, or None.
        """

    def drop(self, plan_id: str, rev: int, sid: str) -> None:
        """Drop a waiting revision.

        Args:
            plan_id: the desk id (pd-...).
            rev: the revision dropped.
            sid: the Claude Code session that drops it.
        """

    def feedback(self, plan_id: str, rev: int, sid: str, text: str) -> None:
        """Keep the user's words on a revision.

        Args:
            plan_id: the desk id (pd-...).
            rev: the revision they are about.
            sid: the Claude Code session they were given in.
            text: the user's words.
        """

    def unread(self, plan_id: str, since: int) -> list[str]:
        """Feedback on the plan not answered since the revision since.

        Args:
            plan_id: the desk id (pd-...).
            since: the time in ms the newest revision was kept.

        Returns:
            The texts of the feedback, oldest first.
        """

    def waiting(self) -> list[Revision]:
        """The revisions waiting for their approval.

        Returns:
            Each waiting Revision, with its question set.
        """

    def approve(self, sid: str, waiting: Revision, by: str = "") -> int:
        """Open an approved revision in the session; its plan number.

        Args:
            sid: the Claude Code session the user approved it in.
            waiting: the waiting Revision approved.
            by: "" for the user's form; else what approved it (a child's card plan: the grant of its parent).

        Returns:
            The plan number in rec_plans.
        """


class TicketStore(Protocol):
    """The run of an approved plan: its commits, its steps, its close and its delivery."""

    def note_commit(self, sid: str, plan: ApprovedPlan, repo: str, sha: str) -> None:
        """Keep a commit git.commit made; step_done adopts it.

        Args:
            sid: the Claude Code session whose ticket notes it.
            plan: the plan in force.
            repo: the repository of the commit.
            sha: the commit.
        """

    def step_commit(self, sid: str, ticket: Ticket, plan: ApprovedPlan, repo: str, sha: Optional[str],
                    fixing: bool) -> Ticket:
        """Keep the step's commit and move the ticket on; the ticket after.

        Args:
            sid: the Claude Code session whose ticket moves.
            ticket: the ticket as the caller saw it.
            plan: the plan in force.
            repo: the repository of the commit.
            sha: the step's commit, or None when the commits git.commit noted are adopted.
            fixing: True for a fix commit: the ticket stays in deliver.

        Returns:
            The ticket after the move.
        """

    def step_skip(self, sid: str, ticket: Ticket, plan: ApprovedPlan, ids: list[str], why: str) -> Ticket:
        """Give the current step up; the ticket after.

        Args:
            sid: the Claude Code session whose ticket moves.
            ticket: the ticket as the caller saw it.
            plan: the plan in force.
            ids: the ids of the step's behaviours, kept skipped.
            why: the reason given.

        Returns:
            The ticket after the move.
        """

    def close_plan(self, sid: str, ticket: Ticket, reason: str, facts: list[str]) -> None:
        """Close the ticket's plan as the user answered the close form.

        Args:
            sid: the Claude Code session whose ticket closes.
            ticket: the ticket as the caller saw it.
            reason: delivered or abandoned.
            facts: the lines of facts the close form showed.
        """

    def holder(self, plan_id: str) -> Optional[Ticket]:
        """The newest ticket that holds the desk plan, open or closed, or None.

        Args:
            plan_id: the desk id (pd-...).

        Returns:
            The newest Ticket whose draft is plan_id, or None.
        """

    def end_plan(self, plan: Revision, how: str, abandon: bool = False) -> None:
        """End a desk plan with the event how (delivered or dropped).

        Args:
            plan: the open desk plan (a Revision with ref).
            how: the event written, delivered or dropped.
            abandon: True to close its open ticket abandoned.
        """

    def back(self, sid: str) -> None:
        """Send a ticket in deliver back to execute.

        Args:
            sid: the Claude Code session whose ticket goes back.
        """

    def deliver(self, sid: str, plan: ApprovedPlan, repo: str, sha: str) -> None:
        """Keep the plan's commit and close its ticket delivered.

        Args:
            sid: the Claude Code session of the delivery.
            plan: the plan delivered.
            repo: the repository of the commit.
            sha: the commit that delivers it.
        """
