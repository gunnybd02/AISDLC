"""Ports: what a run reads from outside and writes back.

LedgerPort keeps the plans of the harness in the ledger (state/harness.db). It is built in three files, each a whole
class: the plumbing (ledger_core.py LedgerCore: the path, write, rows, read, the event of a desk plan), the desk plans
before approval (desk_port.py DeskPort: present, drop, approve, feedback, prompt) and the tickets once a plan is in
force (ticket_port.py TicketPort: step commits, skips, close, delivery). Here, the rest:
- approved: the plan a session works under: the plan of its ticket while the ticket holds one in force
  (utils/plan/tickets.py, approved_plan, the one rule); its file grants, its behaviour registry, its verify receipts;
- the sessions (which one is at work), the rule decisions of a hook call, the doors of the CLI.
The audit rows are never changed after they are written; a ticket is the one body that changes, in place. Reading never
creates the ledger. utils/shapes.py PlanStore describes this port for utils, gear and mcp.

PlanState gives the gears the approved plan of the event's session, and the harness's own state folder."""
from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Optional

from harness.assemble.engine.config import Config, ConfigError
from harness.assemble.engine.desk_port import DeskPort
from harness.assemble.engine.ledger_core import now
from harness.assemble.engine.ticket_port import TicketPort
from harness.utils.contracts import Event, Finding, Port
from harness.utils.git.branches import DEFAULT_PROTECTED, current, is_protected
from harness.utils.git.facts import top, unpushed_files
from harness.utils.plan import grants, stop, tickets
from harness.utils.plan.verify import dirty
from harness.utils.plan.files import key, relative
from harness.utils.ledger import store
from harness.utils.ledger.recorder import Recorder
from harness.utils.shapes import ApprovedPlan, Behaviour, Facts, Grant, PlanStore, Receipt, Ticket


# The ports an MCP action may name in needs (built in wire_mcp.ports_of); the server adds the judge, which run uses for
# a write action. The doctor checks every action's needs against SERVER_PORTS.
ACTION_PORTS = ("plans", "ledger", "verify_command", "items", "doctor", "git_judge", "session", "commit_judge",
                "banned", "store")
SERVER_PORTS = ACTION_PORTS + ("judge",)


class LedgerPort(DeskPort, TicketPort):
    """The ledger port: the desk plans (DeskPort), the tickets (TicketPort), and here the sessions, the plan in force
    with its grants, registry and receipts, and the rows of the CLI doors and of the rules' decisions."""

    def touch_session(self, sid: str) -> None:
        """The session is at work now: the hook saw its prompt, or its call of the harness's MCP tools.

        Args:
            sid: the session id ("" changes nothing).
        """
        if sid:
            self.write(lambda con, rec: con.execute(
                "INSERT INTO sessions (sid, started_at, last_at) VALUES (?, ?, ?) ON CONFLICT(sid) DO UPDATE SET "
                "last_at = excluded.last_at", (sid, now(), now())))

    def session(self) -> str:
        """The session calling the MCP server: the one whose call of the harness's tools the hook saw last ("" if none).
        Claude Code tells an MCP server no session; the hook sees each tool call just before the server runs it.

        Returns:
            The session id, or "".
        """
        rows = self.rows("SELECT sid FROM sessions ORDER BY last_at DESC, rowid DESC LIMIT 1")
        return rows[0]["sid"] if rows else ""

    def ticket(self, sid: str) -> Optional[Ticket]:
        """The newest ticket of the session, or None.

        Args:
            sid: the session id.

        Returns:
            Its newest Ticket, open or closed, or None.
        """
        return self.read(lambda con: tickets.latest(con, sid))

    def approved(self, sid: str) -> Optional[ApprovedPlan]:
        """The plan in force in the session: the plan of its newest ticket, while that ticket holds one, with its file
        grants [(op, path from its root)] in the order they were given (pl_file_grants). None else.

        Args:
            sid: the session id.

        Returns:
            The ApprovedPlan with its grants, or None.
        """
        plan = tickets.approved_plan(self.ticket(sid))
        return {**plan, "grants": self.grants(plan)} if plan else None

    def grants(self, plan: ApprovedPlan) -> list[Grant]:
        """The file grants of the plan, in the order given; a grant outside the plan's root is left out.

        Args:
            plan: the plan in force (ApprovedPlan: id and root are read).

        Returns:
            Each grant as (op, path from the root with forward slashes); op is add or drop.
        """
        out = []
        for r in self.rows("SELECT op, file FROM pl_file_grants WHERE plan_id = ? ORDER BY rowid", (plan["id"],)):
            rel = relative(r["file"], plan["root"])
            if rel is not None:
                out.append((r["op"], rel.replace("\\", "/")))
        return out

    def approved_plan(self, plan_id: str) -> Optional[ApprovedPlan]:
        """The plan in force whose desk id is plan_id (pd-...), whatever its session; None when no open ticket holds it.

        Args:
            plan_id: the desk id.

        Returns:
            The ApprovedPlan (without its grants), or None.
        """
        return tickets.approved_plan(self.read(lambda con: tickets.open_with_draft(con, plan_id)))

    def protected(self, branch: str) -> bool:
        """Whether the branch is protected (the config's protected; main and master when it cannot be read).

        Args:
            branch: the branch name (refs/heads/ may lead).

        Returns:
            True when a protected name or pattern matches it.
        """
        try:
            patterns = Config.load(self.path.parent.parent).protected
        except ConfigError:
            patterns = DEFAULT_PROTECTED
        return is_protected(branch, patterns)

    def registry(self, plan: ApprovedPlan) -> dict[str, Behaviour]:
        """The behaviour registry of the plan (utils/plan/grants.replay), from pl_behaviors in the order written.

        Args:
            plan: the plan in force (ApprovedPlan); the rows of its first revision (rootId) count too.

        Returns:
            {behaviour id: Behaviour}.
        """
        ids = sorted({plan["id"], plan.get("rootId", plan["id"])})
        rows = self.rows(f"SELECT op, id, entry FROM pl_behaviors WHERE plan_id IN ({', '.join('?' * len(ids))}) "
                         "ORDER BY rowid", ids)
        return grants.replay([(r["op"], r["id"], r["entry"]) for r in rows])

    def changed_files(self, plan: ApprovedPlan) -> list[str]:
        """The files of the plan's root that differ from HEAD (utils/plan/verify.dirty).

        Args:
            plan: the plan in force (ApprovedPlan).

        Returns:
            Their paths from the plan's root.
        """
        return dirty(plan)

    def door(self, sid: str, plan: ApprovedPlan, grants: tuple | list = (), behaviors: tuple | list = ()) -> None:
        """The rows of one CLI door, in one transaction: file grants (op, absolute path, why) and behaviour rows
        (op, id, entry), all chained.

        Args:
            sid: the session of the door.
            plan: the plan in force (ApprovedPlan).
            grants: (op, absolute path, why) of each file grant; op add or drop.
            behaviors: (op, behaviour id, entry dict) of each behaviour row; op add, retire...
        """
        def change(con: sqlite3.Connection, rec: Recorder) -> None:
            for op, path, why in grants:
                rec.insert(con, "pl_file_grants", {"uid": uuid.uuid4().hex, "sid": sid, "plan_id": plan["id"],
                                                   "op": op, "file": path, "why": why, "at": now()})
            for op, bid, entry in behaviors:
                rec.insert(con, "pl_behaviors", {"uid": uuid.uuid4().hex, "sid": sid, "plan_id": plan["id"],
                                                 "repo": plan["root"], "op": op, "id": bid,
                                                 "entry": json.dumps(entry, ensure_ascii=False), "at": now()})
        self.write(change)

    def is_home(self, repo: str) -> bool:
        """Whether repo is the home, the repository that holds the harness.

        Args:
            repo: a folder.

        Returns:
            True when repo is in the git repository of the home.
        """
        home, here = top(self.path.parent.parent), top(repo) if Path(repo).is_dir() else None
        return bool(home and here) and key(home) == key(here)

    def decision(self, event: Event, plan: Optional[ApprovedPlan], finding: Finding, verdict: str) -> None:
        """Keep one finding of a hook call with the word Claude Code was given (act_rule_decisions).

        Args:
            event: the hook call.
            plan: the plan in force in its session, or None.
            finding: the finding kept.
            verdict: the word Claude Code was given for the call (contracts.CLAUDE_DECISION, or the decision itself).
        """
        self.write(lambda con, rec: rec.insert(con, "act_rule_decisions", {
            "uid": uuid.uuid4().hex, "sid": event.session, "agent": "", "plan_id": plan["id"] if plan else None,
            "rule": finding.kind, "kind": "finding", "tool": event.tool, "service": "", "verdict": verdict,
            "detail": finding.detail, "at": now()}))

    def keep_verify(self, plan: ApprovedPlan, receipt: Receipt) -> None:
        """A verify receipt of an approved plan: {files: {path: blob id}, tests, commands, code, ok, why, ms}.

        Args:
            plan: the plan verified (ApprovedPlan); its tests are kept with the receipt.
            receipt: the Receipt of the run (files, commands, code, ok, why, ms).
        """
        self.write(lambda con, rec: rec.insert(con, "pl_verify", {
            "uid": uuid.uuid4().hex, "sid": "", "plan_id": plan["id"], "repo": plan["root"],
            "files": json.dumps(receipt["files"]), "tests": json.dumps(plan.get("tests", [])),
            "commands": json.dumps(receipt["commands"]), "code": receipt["code"], "ok": int(receipt["ok"]),
            "why": receipt["why"], "ms": receipt["ms"], "at": now()}))

    def green_receipt(self, plan: ApprovedPlan) -> Optional[Receipt]:
        """The newest green receipt of the plan, or None.

        Args:
            plan: the plan in force (ApprovedPlan).

        Returns:
            {ok: 1, files: {path: blob id}}, or None when no verify of it passed.
        """
        row = next(iter(self.rows("SELECT files FROM pl_verify WHERE plan_id = ? AND ok = 1 ORDER BY at DESC, rowid DESC "
                                  "LIMIT 1", (plan["id"],))), None)
        return {"ok": 1, "files": json.loads(row["files"])} if row else None

    def receipt(self, plan: ApprovedPlan) -> Optional[Receipt]:
        """The newest receipt of the plan, green or not, or None.

        Args:
            plan: the plan in force (ApprovedPlan).

        Returns:
            {ok, files: {path: blob id}}, or None when it was never verified.
        """
        row = next(iter(self.rows("SELECT ok, files FROM pl_verify WHERE plan_id = ? ORDER BY at DESC, rowid DESC "
                                  "LIMIT 1", (plan["id"],))), None)
        return {"ok": row["ok"], "files": json.loads(row["files"])} if row else None

    def committed(self, sha: str) -> bool:
        """Whether the ledger keeps the commit sha (rec_commits).

        Args:
            sha: the commit.

        Returns:
            True when some plan's commit is sha.
        """
        return bool(self.rows("SELECT 1 FROM rec_commits WHERE commit_sha = ?", (sha,)))


class GitView:
    """The git facts of the git rules (gear/detect/git.py), each read only when a command needs it: the branch a
    repository is on, whether a branch is protected, what a push would send, whether a repository is the home."""

    def __init__(self, claude_dir: str | Path, protected: Iterable[str]) -> None:
        """Keep the home and the protected branches.

        Args:
            claude_dir: the home, the .claude folder of the harness.
            protected: the protected branch names or fnmatch patterns.
        """
        self.claude_dir, self.patterns = Path(claude_dir), tuple(protected)

    def branch_of(self, repo: str) -> str:
        """The branch the repository is on.

        Args:
            repo: a folder.

        Returns:
            The branch, or "" (detached, no repository, or no such folder).
        """
        return current(repo) if Path(repo).is_dir() else ""

    def protected(self, branch: str) -> bool:
        """Whether the branch is protected.

        Args:
            branch: the branch name.

        Returns:
            True when a protected name or pattern matches it.
        """
        return is_protected(branch, self.patterns)

    def unpushed(self, repo: str, remote: str, source: str) -> list[str]:
        """What a push of source to remote would send.

        Args:
            repo: the repository.
            remote: the remote pushed to.
            source: the ref pushed.

        Returns:
            The paths its commits change that no ref of remote holds yet; [] when repo is no folder.
        """
        return unpushed_files(repo, remote, source) if Path(repo).is_dir() else []

    def is_home(self, repo: str) -> bool:
        """Whether repo is the home, the repository that holds the harness.

        Args:
            repo: a folder.

        Returns:
            True when repo is in the git repository of the home.
        """
        home = top(self.claude_dir)
        here = top(repo) if Path(repo).is_dir() else None
        return bool(home and here) and key(home) == key(here)


class PlanState(Port):
    """The gears' view of the world: the approved plan, the harness's own state folder, and the git facts (GitView)."""

    def __init__(self, port: PlanStore, protected: Iterable[str] = DEFAULT_PROTECTED,
                 banned: Iterable[str] = ()) -> None:
        """Keep the ledger port, the git facts of the home and the banned words.

        Args:
            port: the ledger port (LedgerPort).
            protected: the protected branch names or patterns.
            banned: the words commit and merge request text never hold.
        """
        self.port, self.git, self.banned = port, GitView(Path(port.path).parent.parent, protected), tuple(banned)

    def read(self, event: Event) -> Facts:
        """The facts of the event's session: plan (ApprovedPlan or None), state_dir, git_view (GitView), stop_owed
        (plan -> code files no green verify saw), banned, store_owed (() -> the unsaved work of the store)."""
        return {"plan": self.port.approved(event.session), "state_dir": str(self.port.path.parent).replace("\\", "/"),
                "git_view": self.git, "stop_owed": lambda plan: stop.unverified(self.port, plan), "banned": self.banned,
                "store_owed": lambda: store.owed(self.port) if store.folder() else []}
