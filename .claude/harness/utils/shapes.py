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
| GitCommit, GitFacts | the facts git_commit and git_view of a hook call | gear/translate/git.py, assemble |
| GitJudge, CommitJudge | the rules' verdict on a git command, on a commit | assemble/engine/wire_mcp.py |
| PlanStore | the ledger port; its parts and their methods are in shapes_store.py | assemble/engine/ports.py |
| Card, ChildGrant, CrewEntry, ChildRole | a child of a plan, the grant, a started child, a child's own role | utils/orchestra |
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol, TypedDict, TypeVar

from harness.utils.shapes_store import DeskStore, LedgerAccess, PlanFacts, TicketStore

if TYPE_CHECKING:
    from harness.utils.contracts import Verdict
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

RawChange = tuple[Optional[str], Optional[str], Optional[str]]
"""(old mode, new mode, new blob id) of one path a git diff changes (utils/git/facts.py raw_changes); a mode is None
where the path is absent, the blob None when the change deletes it."""


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


class Card(TypedDict, total=False):
    """One child of a delegated plan (utils/orchestra/card.py; docs/05-orchestra.md section 5.1): name (a-z, 0-9, -),
    unit (home or a declared unit), goal (one sentence), ac (1 to 6 criteria), the paths to read, change and test, the
    acceptance tests the parent writes and locks before the child starts (acTests, utils/orchestra/locked.py), the
    name of an open session to adopt, and actions (only push)."""
    name: str
    unit: str
    goal: str
    ac: list[str]
    read: list[str]
    change: list[str]
    tests: list[str]
    acTests: list[str]
    session: str
    actions: list[str]


class ChildGrant(TypedDict):
    """What the user approves for the children with a delegated plan (utils/orchestra/card.grant): the units they may
    touch (home left out), how many children, a copy of every card, and the actions of each card by name."""
    units: list[str]
    count: int
    cards: list[Card]
    actions: dict[str, list[str]]


class ChildRole(TypedDict):
    """What makes a session a child (utils/orchestra/child.py): its brief, its first prompt, named the child and the
    parent plan's number; draft the parent plan's desk id; parent the parent's session; branch the one it works and
    pushes on (orch/p<plan>/<name>); its card; the behaviour id of each criterion (p<plan>.<name>.ac<n>); its unit
    {repo, path, verify, base} (utils/orchestra/card.unit_spec); start the plan branch it starts from ("": the base)."""
    name: str
    plan: int
    draft: str
    parent: str
    branch: str
    card: Card
    behaviours: list[str]
    unit: dict[str, Any]
    start: str


class CrewEntry(TypedDict, total=False):
    """A started child on its parent's delegated ticket (utils/orchestra/crew.py): unit; sid its cloud session;
    state (running, handed back, accepted, forgotten, released, removed); backs the rounds it was sent back;
    checkedAt the round of its last green check; adopted (an open session taken on); model; reportSid the parent's
    session; at when it started and sentBackAt when it was last sent back (ms); sent the texts delivered to it;
    lastCheck {green, at, lines} of the parent's check; pr {number, url, repo, base} once accepted; merged {sha, at}
    once land merged it; forgotWhy, releasedWhy; receipt, the child's receipt as check read it; fresh {note, at} while
    it waits for a fresh session after a send-back or an answer on its branch; sessions, its earlier sessions
    (utils/orchestra/review.py, land.py, cleanup.py)."""
    unit: str
    sid: str
    state: str
    backs: int
    checkedAt: Optional[int]
    adopted: bool
    model: str
    reportSid: str
    at: int
    sentBackAt: Optional[int]
    sent: list[dict[str, Any]]
    fresh: dict[str, Any]
    sessions: list[str]
    lastCheck: dict[str, Any]
    pr: dict[str, Any]
    merged: dict[str, Any]
    forgotWhy: str
    releasedWhy: str
    receipt: dict[str, Any]


class PlanItems(TypedDict, total=False):
    """A plan as presented and kept (utils/plan/desk.py KEYS). A light plan holds title, what, files and tests; a full
    plan also steps, overview, code, services, checks, assumptions, notDoing and risks. repos names the repositories
    the plan works on ({name: {url, base?, verify?, path?, pipeline?}}), limits may lower the orchestra limits. root is
    the folder the plan's paths are relative to, and verify the test command of the repository root is in (from
    repos): both set by the server, never by the model."""
    title: str
    overview: dict[str, list[str]]
    code: list[dict[str, str]]
    test: list[dict[str, Any]]
    repos: dict[str, dict[str, Any]]
    limits: dict[str, int]
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
    children: list[Card]
    teamSkills: list[str]
    assumptions: list[str]
    notDoing: list[str]
    risks: list[str]
    root: str
    verify: list[str]


class Revision(TypedDict, total=False):
    """A kept revision of a desk plan (pl_plan_revs) with its newest event (pl_plan_events): plan_id is the desk id
    (pd-...), rev the revision number, sid the session that presented it, sha the hash of its items, at the time in ms,
    revisions how many it has, event and event_rev the newest event and the revision it was for. question is added
    for a waiting revision: the form question that approves it; ref for an open plan (utils/plan/life.py): the plan
    number of its newest approval, or None."""
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
    ref: Optional[int]


class ApprovedPlan(PlanItems, total=False):
    """The plan in force under a ticket: its items plus type, id (rec_plans), plan_id (desk id), rev, base (the commit
    at the approval, or None), sha (of the items), rootId (the first plan number) and its file grants (approved())."""
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
    abandoned, superseded); what a superseded ticket carried over (priorCommits, spentPlan); backs how many times a
    write sent it back from deliver to execute, and backTold, set False each time it goes back. A delegated ticket
    (a plan with children) also holds the grant, its crew (the started children by name), the lock of its acceptance
    tests (orchestra/locked.py) and its issues and ticket file (orchestra/issues.py); a child's ticket holds its role
    (child), the questions it asked (asks) and its last handback ({sha, at}) (utils/orchestra)."""
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
    backs: int
    backTold: bool
    grant: ChildGrant
    crew: dict[str, CrewEntry]
    lock: dict[str, Any]
    issues: dict[str, Any]
    child: ChildRole
    asks: list[dict[str, Any]]
    handback: dict[str, Any]


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


class GitCommit(TypedDict):
    """A shell line that may commit (the fact git_commit, gear/translate/git.py): repo the repository (forward
    slashes), unsafe why the gate cannot see the whole commit ("" for one plain safe commit)."""
    repo: str
    unsafe: str


class GitFacts(Protocol):
    """The git facts of a hook call (the fact git_view; assemble/engine/ports.py GitView), each read only when called."""

    def branch_of(self, repo: str) -> str:
        """The branch the repository is on.

        Args:
            repo: the repository's folder.

        Returns:
            The branch name; "" when repo is not a folder.
        """

    def protected(self, branch: str, repo: str = "") -> bool:
        """Whether the branch is protected (main and master always; the configured ones; those the forge protects in
        repo).

        Args:
            branch: a branch name.
            repo: the repository the branch is in; "" asks no forge.

        Returns:
            True for a protected branch.
        """

    def unpushed(self, repo: str, remote: str, source: str) -> list[str]:
        """The files of the commits a push of source to remote would send.

        Args:
            repo: the repository's folder.
            remote: the remote's name or URL.
            source: the local ref the push sends.

        Returns:
            The paths those commits change.
        """

    def is_home(self, repo: str) -> bool:
        """Whether repo is the repository that holds the harness.

        Args:
            repo: a repository's folder.

        Returns:
            True for the home.
        """


class GitJudge(Protocol):
    """judge(repo, words): the rules' verdict on running `git <words>` in the repository repo (wire_mcp git_event)."""

    def __call__(self, repo: str, words: list[str]) -> Verdict:
        """Judge one git command; the verdict says whether it may run, needs the user's word, or may not.

        Args:
            repo: the repository the command runs in.
            words: the words after `git`.

        Returns:
            The rules' verdict on the event HarnessGit.
        """


class CommitJudge(Protocol):
    """judge(repo, files, message): the rules' verdict on a commit the harness is about to make (secrets, AI marks,
    banned words, agent files; wire_mcp commit_event)."""

    def __call__(self, repo: str, files: list[str], message: str) -> Verdict:
        """Judge one commit before it is made.

        Args:
            repo: the repository's root.
            files: the paths to commit, from the repository root.
            message: the commit message.

        Returns:
            The rules' verdict on the event HarnessCommit.
        """


class PlanStore(LedgerAccess, PlanFacts, DeskStore, TicketStore, Protocol):
    """The ledger port as utils, gear and mcp use it (assemble/engine/ports.py LedgerPort): the ledger's rows, the
    plans, tickets, receipts and registry of the sessions. Every write is one transaction. Its methods are documented
    by part in shapes_store.py (LedgerAccess, PlanFacts, DeskStore, TicketStore)."""
