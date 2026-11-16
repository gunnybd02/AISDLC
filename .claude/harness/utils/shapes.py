"""Shapes: the names of the data the harness passes around, so a function says in its hints what it takes and gives.

Most of the harness's data are plain dicts (JSON in the ledger, facts of a hook call); a TypedDict here names the keys
of each kind. total=False means a key may be missing. The ports are Protocols: utils and gear name the ledger port
without importing assemble, where it is built (assemble/engine/ports.py LedgerPort). Nothing here runs: these are
types and their documentation only.

| Shape | What it is | Made by |
|---|---|---|
| PlanItems | a plan as presented: title, what, files, tests, steps... | utils/plan/desk.py |
| Step, PlanBehaviour | one step of a plan, one behaviour named in it | utils/plan/desk.py |
| Revision | a kept revision of a desk plan and its newest event | utils/plan/revisions.py |
| ApprovedPlan | the plan in force under a ticket | utils/plan/opening.py |
| Ticket | the run of one approved plan, from approval to close | utils/plan/tickets.py |
| Behaviour | an entry of the behaviour registry of a plan | utils/plan/grants.py |
| Receipt | the result of one verify run | utils/plan/verify.py |
| StoreRecord, ExportCopy, SavedCopy | a ledger copy for the store, and what the store holds | utils/ledger/store.py |
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol, TypedDict, TypeVar

if TYPE_CHECKING:
    from harness.utils.contracts import Event, Finding, Verdict
    from harness.utils.ledger.recorder import Recorder

T = TypeVar("T")

Row = dict[str, Any]
"""One row of a ledger query, by column name (sqlite3.Row turned into a dict)."""

Facts = dict[str, Any]
"""What the translators and ports say about one hook call, by fact name; each fact has one giver (runner.py)."""

Grant = tuple[str, str]
"""A file grant of an approved plan: (op, path from the plan's root); op is "add" or "drop"."""

Change = Callable[[sqlite3.Connection, "Recorder"], T]
"""A write to the ledger: change(con, rec) runs inside one transaction; rec inserts rows (chained ones too)."""


class PlanBehaviour(TypedDict, total=False):
    """A behaviour as a plan names it: id like "a.b-c" (in a step: "s<n>.<id>"), what it does, how it is proven,
    why it matters, its test file, and its step number (from 1)."""
    id: str
    what: str
    how: str
    why: str
    test: str
    step: int


class Step(TypedDict, total=False):
    """One step of a full plan: the message of its commit, its points, the files it changes and their tests."""
    commit: str
    points: list[str]
    files: list[str]
    tests: list[str]
    behaviors: list[PlanBehaviour]


class PlanItems(TypedDict, total=False):
    """A plan as presented and kept (utils/plan/desk.py KEYS). A light plan holds title, what, files and tests; a full
    plan also steps, overview, code, services, checks, assumptions, notDoing and risks. root is the folder the plan's
    paths are relative to, set by the server, never by the model."""
    title: str
    overview: dict[str, list[str]]
    code: list[dict[str, str]]
    test: list[dict[str, Any]]
    services: list[str]
    branch: str
    what: list[str]
    files: list[str]
    tests: list[str]
    checks: list[str]
    commit: str
    steps: list[Step]
    behaviors: list[PlanBehaviour]
    network: list[dict[str, Any]]
    commands: list[str]
    children: list[dict[str, Any]]
    teamSkills: list[str]
    assumptions: list[str]
    notDoing: list[str]
    risks: list[str]
    root: str


class Revision(TypedDict, total=False):
    """A kept revision of a desk plan (pl_plan_revs) with its newest event (pl_plan_events): plan_id is the desk id
    (pd-...), rev the revision number, sid the session that presented it, sha the hash of its items, at the time in ms,
    revisions how many it has, event and event_rev the newest event and the revision it was for. question is added
    for a waiting revision: the form question that approves it."""
    plan_id: str
    rev: int
    sid: str
    items: PlanItems
    sha: str
    at: int
    revisions: int
    event: Optional[str]
    event_rev: Optional[int]
    question: str


class ApprovedPlan(PlanItems, total=False):
    """The plan in force under a ticket: the approved items plus type ("ApprovedPlan"), id (the plan number in
    rec_plans), plan_id (the desk id), rev, base (the commit its repository stood on at the approval, or None), sha
    (of the items), rootId (the first plan number across revisions) and, from LedgerPort.approved, its file grants."""
    type: str
    id: int
    plan_id: str
    rev: int
    base: Optional[str]
    sha: str
    rootId: int
    grants: list[Grant]


class Ticket(TypedDict, total=False):
    """The run of one approved plan (pl_tickets body; utils/plan/tickets.py): state open or closed; phase prepare,
    execute or deliver; the plan in force; draft (the desk id) and rootId; step (from 0); the commits, skips and done
    steps; noted (commits git.commit made, waiting for step_done); stepCommits by step; closeReason (delivered,
    abandoned, superseded); what a superseded ticket carried over (priorCommits, spentPlan)."""
    id: str
    sid: str
    seq: int
    state: str
    phase: str
    plan: Optional[ApprovedPlan]
    draft: Optional[str]
    rootId: Optional[int]
    step: int
    commits: list[str]
    skips: int
    doneSteps: list[int]
    priorCommits: list[str]
    closeReason: Optional[str]
    noted: list[str]
    stepCommits: dict[str, list[str]]
    spentPlan: int
    freshApproval: bool
    units: list[str]


class Behaviour(TypedDict, total=False):
    """An entry of a plan's behaviour registry (utils/plan/grants.replay): what, how and why; tests as "file" or
    "file#test_name"; status active, pending, skipped or retired; the plan number and step it belongs to."""
    what: str
    how: str
    why: str
    tests: list[str]
    status: str
    plan: int
    step: Optional[int]


class Receipt(TypedDict, total=False):
    """The result of one verify run (pl_verify): files maps each path from the plan's root to the git blob id the
    tests saw; commands the command run; code its exit code; ok whether it passed; why the reason when it did not;
    ms how long it took. A receipt read back for a check holds only ok and files."""
    files: dict[str, str]
    commands: list[list[str]]
    code: int
    ok: int
    why: str
    ms: int


class StoreRecord(TypedDict, total=False):
    """The record of one ledger copy for the store (pl_notes kind store.export; utils/ledger/store.py): ledger is the
    ledger's id, seq the copy's number in it, title the file name, session the Claude Code session, reason manual,
    push, plan-close or turn-end, at the time in ms, commit the newest commit (7 characters, or "nocommit"), schema
    "s" and 8 characters of the schema's fingerprint, mark the counts [commits, plan events, pushes] the copy holds,
    repo and branch where the copy was asked from."""
    ledger: str
    seq: int
    title: str
    session: str
    reason: str
    at: int
    commit: str
    schema: str
    mark: list[int]
    repo: str
    branch: str


class ExportCopy(TypedDict):
    """A copy made for the store (utils/ledger/export.snapshot): its absolute path (posix), its file name, the sha256
    of its bytes (the Drive tool's file reference needs it) and its size in bytes."""
    path: str
    title: str
    sha256: str
    size: int


class SavedCopy(TypedDict):
    """The newest copy the store holds (utils/ledger/store.saved): its number, file name, the Drive file's id, the
    mark it holds and when the upload was seen (ms)."""
    seq: int
    title: str
    file_id: str
    mark: list[int]
    at: int


class GitJudge(Protocol):
    """judge(repo, words): the rules' verdict on running `git <words>` in the repository repo (wire_mcp git_event)."""

    def __call__(self, repo: str, words: list[str]) -> Verdict:
        """Judge one git command; the verdict says whether it may run, needs the user's word, or may not."""
        ...


class CommitJudge(Protocol):
    """judge(repo, files, message): the rules' verdict on a commit the harness is about to make (secrets, AI marks,
    banned words, agent files; wire_mcp commit_event)."""

    def __call__(self, repo: str, files: list[str], message: str) -> Verdict:
        """Judge one commit before it is made."""
        ...


class PlanStore(Protocol):
    """The ledger port as utils, gear and mcp use it (assemble/engine/ports.py LedgerPort): the ledger's rows, the
    plans, tickets, receipts and registry of the sessions. Every write is one transaction."""
    path: Path

    def rows(self, sql: str, args: tuple | list = ()) -> list[Row]:
        """The rows of one read query; [] when there is no ledger yet."""
        ...

    def write(self, change: Change[T]) -> T:
        """Run change(con, rec) in one transaction and give back what it returns."""
        ...

    def read(self, look: Callable[[sqlite3.Connection], T]) -> Optional[T]:
        """look(con) on the ledger, or None when there is no ledger yet."""
        ...

    def touch_session(self, sid: str) -> None:
        """Mark the session as the one at work now."""
        ...

    def session(self) -> str:
        """The session the hook saw last ("" when none)."""
        ...

    def ticket(self, sid: str) -> Optional[Ticket]:
        """The newest ticket of the session, or None."""
        ...

    def present(self, items: PlanItems, plan_id: Optional[str] = None, sid: str = "",
                why: Optional[dict] = None) -> tuple[str, int, str]:
        """Keep a revision of a desk plan: (plan id, revision, the form question)."""
        ...

    def revision(self, plan_id: str) -> Optional[Revision]:
        """The newest revision of a desk plan, or None."""
        ...

    def drop(self, plan_id: str, rev: int, sid: str) -> None:
        """Drop a waiting revision."""
        ...

    def feedback(self, plan_id: str, rev: int, sid: str, text: str) -> None:
        """Keep the user's words on a revision."""
        ...

    def unread(self, plan_id: str, since: int) -> list[Row]:
        """Feedback on the plan not answered since the revision since."""
        ...

    def waiting(self) -> list[Revision]:
        """The revisions waiting for their approval, each with its question."""
        ...

    def approve(self, sid: str, waiting: Revision) -> int:
        """Open an approved revision in the session; its plan number."""
        ...

    def approved(self, sid: str) -> Optional[ApprovedPlan]:
        """The plan in force in the session with its grants, or None."""
        ...

    def grants(self, plan: ApprovedPlan) -> list[Grant]:
        """The file grants of the plan, in the order given."""
        ...

    def approved_plan(self, plan_id: str) -> Optional[ApprovedPlan]:
        """The plan in force whose desk id is plan_id, whatever its session, or None."""
        ...

    def protected(self, branch: str) -> bool:
        """Whether the branch is protected."""
        ...

    def registry(self, plan: ApprovedPlan) -> dict[str, Behaviour]:
        """The behaviour registry of the plan: {behaviour id: entry}."""
        ...

    def changed_files(self, plan: ApprovedPlan) -> list[str]:
        """The files of the plan's root that differ from HEAD."""
        ...

    def door(self, sid: str, plan: ApprovedPlan, grants: tuple | list = (), behaviors: tuple | list = ()) -> None:
        """Keep the rows of one CLI door: file grants (op, path, why) and behaviour rows (op, id, entry)."""
        ...

    def is_home(self, repo: str) -> bool:
        """Whether repo is the repository that holds the harness."""
        ...

    def note_commit(self, sid: str, plan: ApprovedPlan, repo: str, sha: str) -> None:
        """Keep a commit git.commit made; step_done adopts it."""
        ...

    def step_commit(self, sid: str, ticket: Ticket, plan: ApprovedPlan, repo: str, sha: Optional[str],
                    fixing: bool) -> Ticket:
        """Keep the step's commit and move the ticket on; the ticket after."""
        ...

    def step_skip(self, sid: str, ticket: Ticket, plan: ApprovedPlan, ids: list[str], why: str) -> Ticket:
        """Give the current step up; the ticket after."""
        ...

    def close_plan(self, sid: str, ticket: Ticket, reason: str, facts: dict) -> None:
        """Close the ticket's plan as the user answered the close form."""
        ...

    def holder(self, plan_id: str) -> Optional[Ticket]:
        """The newest ticket that holds the desk plan, open or closed, or None."""
        ...

    def end_plan(self, plan: Revision, how: str, abandon: bool = False) -> None:
        """End a desk plan with the event how (delivered or dropped)."""
        ...

    def back(self, sid: str) -> None:
        """Send a ticket in deliver back to execute."""
        ...

    def decision(self, event: Event, plan: Optional[ApprovedPlan], finding: Finding, verdict: str) -> None:
        """Keep one finding of a hook call with the word Claude Code was given."""
        ...

    def keep_verify(self, plan: ApprovedPlan, receipt: Receipt) -> None:
        """Keep a verify receipt of the plan."""
        ...

    def green_receipt(self, plan: ApprovedPlan) -> Optional[Receipt]:
        """The newest passing receipt of the plan ({ok, files}), or None."""
        ...

    def receipt(self, plan: ApprovedPlan) -> Optional[Receipt]:
        """The newest receipt of the plan ({ok, files}), or None."""
        ...

    def committed(self, sha: str) -> bool:
        """Whether the ledger keeps the commit sha."""
        ...

    def deliver(self, sid: str, plan: ApprovedPlan, repo: str, sha: str) -> None:
        """Keep the plan's commit and close its ticket delivered."""
        ...
