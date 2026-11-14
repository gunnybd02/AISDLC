"""Ports: what a run reads from outside and writes back.

LedgerPort keeps the plans of the harness in the ledger (state/harness.db):
- present: a revision of a desk plan (its items, utils/plan/desk.py, and its root), waiting (pl_plan_revs,
  utils/plan/revisions.py, a 'waiting' event); drop: a waiting plan no longer waits ('dropped');
- approve: the user's "Duyệt" in the form to that revision's question (a chained rec_plans row, an 'approved' event);
- approved: the plan a session works under: the plan of its ticket while the ticket holds one in force
  (utils/plan/tickets.py, approved_plan, the one rule).
The audit rows are never changed after they are written; a ticket is the one body that changes, in place. Reading never
creates the ledger.

PlanState gives the gears the approved plan of the event's session, and the harness's own state folder."""
import hashlib
import json
import time
import uuid
from pathlib import Path

from harness.utils.contracts import YES, Port
from harness.utils.git.branches import DEFAULT_PROTECTED, current, is_protected
from harness.utils.git.facts import head, top, unpushed_files
from harness.utils.plan import render, revisions, tickets
from harness.utils.plan.desk import new_id
from harness.utils.plan.files import key
from harness.utils.ledger.db import Ledger
from harness.utils.ledger.recorder import Recorder


# The ports an MCP action may name in needs (built in wire_mcp.ports_of); the server adds the judge, which run uses for
# a write action. The doctor checks every action's needs against SERVER_PORTS.
ACTION_PORTS = ("plans", "ledger", "verify_command", "items", "doctor", "git_judge", "session")
SERVER_PORTS = ACTION_PORTS + ("judge",)


def question(items, plan_id, rev):
    """The form question of a revision (utils/plan/render.py); the block above it shows what the user approves."""
    return render.question(items, plan_id, rev)


def now():
    return int(time.time() * 1000)


class LedgerPort:
    def __init__(self, claude_dir):
        self.path = Path(claude_dir) / "state" / "harness.db"
        self._ledger = None

    @property
    def ledger(self):
        if self._ledger is None:
            self._ledger = Ledger.open(self.path)
        return self._ledger

    def write(self, change):
        return self.ledger.write(lambda con: change(con, Recorder(self.ledger)))

    def rows(self, sql, args=()):
        return self.ledger.all(sql, args) if self.path.exists() else []

    def read(self, look):
        """look(con) on the ledger, or None when there is no ledger yet (a read never makes one)."""
        return look(self.ledger.con) if self.path.exists() else None

    def touch_session(self, sid):
        """The session is at work now: the hook saw its prompt, or its call of the harness's MCP tools."""
        if sid:
            self.write(lambda con, rec: con.execute(
                "INSERT INTO sessions (sid, started_at, last_at) VALUES (?, ?, ?) ON CONFLICT(sid) DO UPDATE SET "
                "last_at = excluded.last_at", (sid, now(), now())))

    def session(self):
        """The session calling the MCP server: the one whose call of the harness's tools the hook saw last ("" if none).
        Claude Code tells an MCP server no session; the hook sees each tool call just before the server runs it."""
        rows = self.rows("SELECT sid FROM sessions ORDER BY last_at DESC, rowid DESC LIMIT 1")
        return rows[0]["sid"] if rows else ""

    def ticket(self, sid):
        """The newest ticket of the session, or None."""
        return self.read(lambda con: tickets.latest(con, sid))

    def present(self, items, plan_id=None, sid="", why=None):
        """Keep a revision of a desk plan (a new one without plan_id); give (plan id, revision, the form question)."""
        plan_id = plan_id or new_id()

        def change(con, rec):
            rev = revisions.record(con, rec, plan_id, sid, items, why)
            self.event(con, rec, plan_id, "waiting", rev, sid=sid)
            return rev

        rev = self.write(change)
        return plan_id, rev, question(items, plan_id, rev)

    def revision(self, plan_id):
        """The newest revision of a desk plan and its state (utils/plan/revisions.newest), or None."""
        return self.read(lambda con: revisions.newest(con, plan_id))

    def drop(self, plan_id, rev, sid):
        self.write(lambda con, rec: self.event(con, rec, plan_id, "dropped", rev, sid=sid))

    def feedback(self, plan_id, rev, sid, text):
        self.write(lambda con, rec: revisions.feedback(con, plan_id, rev, sid, text))

    def unread(self, plan_id, since):
        return self.read(lambda con: revisions.unread(con, plan_id, since)) or []

    @staticmethod
    def event(con, rec, plan_id, name, rev, ref=None, sid=""):
        n = 1 + (con.execute("SELECT MAX(n) FROM pl_plan_events WHERE plan_id = ?", (plan_id,)).fetchone()[0] or 0)
        rec.insert(con, "pl_plan_events", {"plan_id": plan_id, "n": n, "sid": sid, "event": name, "rev": rev,
                                           "ref": ref, "at": now()})

    def waiting(self):
        """The newest revision of each desk plan that waits for its approval, with its question."""
        return [{**w, "question": question(w["items"], w["plan_id"], w["rev"])}
                for w in self.read(revisions.waiting) or []]

    def approve(self, sid, waiting):
        """The user approved this waiting revision in the session sid. Its root is the one the form showed; base is the
        commit its repository stands on now, which a delivered commit must come from."""
        repo = top(waiting["items"]["root"])
        scope = {"plan_id": waiting["plan_id"], "rev": waiting["rev"], "base": head(repo) if repo else None,
                 **waiting["items"]}

        def change(con, rec):
            rid = rec.insert(con, "rec_plans", {"sid": sid, "sha": hashlib.sha256(json.dumps(scope, sort_keys=True)
                                                                                   .encode()).hexdigest()[:8],
                                                "reason": "form", "scope": json.dumps(scope, ensure_ascii=False),
                                                "services": "[]", "status": "approved", "at": now(),
                                                "uid": uuid.uuid4().hex})
            self.event(con, rec, waiting["plan_id"], "approved", waiting["rev"], rid, sid)
            tickets.open_plan(con, sid, {"id": rid, **scope})
            self.event(con, rec, waiting["plan_id"], "executing", waiting["rev"], rid, sid)
            return rid

        return self.write(change)

    def approved(self, sid):
        """The plan in force in the session: the plan of its newest ticket, while that ticket holds one. None else."""
        return tickets.approved_plan(self.ticket(sid))

    def approved_plan(self, plan_id):
        """The plan in force whose desk id is plan_id (pd-...), whatever its session; None when no open ticket holds it."""
        return tickets.approved_plan(self.read(lambda con: tickets.open_with_draft(con, plan_id)))

    def decision(self, event, plan, finding, verdict):
        self.write(lambda con, rec: rec.insert(con, "act_rule_decisions", {
            "uid": uuid.uuid4().hex, "sid": event.session, "agent": "", "plan_id": plan["id"] if plan else None,
            "rule": finding.kind, "kind": "finding", "tool": event.tool, "service": "", "verdict": verdict,
            "detail": finding.detail, "at": now()}))

    def keep_verify(self, plan, receipt):
        """A verify receipt of an approved plan: {files: {path: blob id}, tests, commands, code, ok, why, ms}."""
        self.write(lambda con, rec: rec.insert(con, "pl_verify", {
            "uid": uuid.uuid4().hex, "sid": "", "plan_id": plan["id"], "repo": plan["root"],
            "files": json.dumps(receipt["files"]), "tests": json.dumps(plan["tests"]),
            "commands": json.dumps(receipt["commands"]), "code": receipt["code"], "ok": int(receipt["ok"]),
            "why": receipt["why"], "ms": receipt["ms"], "at": now()}))

    def receipt(self, plan):
        row = next(iter(self.rows("SELECT ok, files FROM pl_verify WHERE plan_id = ? ORDER BY at DESC, rowid DESC "
                                  "LIMIT 1", (plan["id"],))), None)
        return {"ok": row["ok"], "files": json.loads(row["files"])} if row else None

    def committed(self, sha):
        return bool(self.rows("SELECT 1 FROM rec_commits WHERE commit_sha = ?", (sha,)))

    def deliver(self, sid, plan, repo, sha):
        """The plan's change is committed: keep the commit; its ticket closes delivered (a home plan needs no form)."""
        def change(con, rec):
            rec.insert(con, "rec_commits", {"plan_id": plan["id"], "service": repo, "commit_sha": sha, "at": now(),
                                            "uid": uuid.uuid4().hex})
            ticket = tickets.open_with_draft(con, plan["plan_id"])
            if ticket:
                tickets.deliver(con, ticket, sha)
            self.event(con, rec, plan["plan_id"], "delivered", plan["rev"], plan["id"], ticket["sid"] if ticket else sid)
        self.write(change)


class GitView:
    """The git facts of the git rules (gear/detect/git.py), each read only when a command needs it: the branch a
    repository is on, whether a branch is protected, what a push would send, whether a repository is the home."""

    def __init__(self, claude_dir, protected):
        self.claude_dir, self.patterns = Path(claude_dir), tuple(protected)

    def branch_of(self, repo):
        return current(repo) if Path(repo).is_dir() else ""

    def protected(self, branch):
        return is_protected(branch, self.patterns)

    def unpushed(self, repo, remote, source):
        return unpushed_files(repo, remote, source) if Path(repo).is_dir() else []

    def is_home(self, repo):
        home = top(self.claude_dir)
        here = top(repo) if Path(repo).is_dir() else None
        return bool(home and here) and key(home) == key(here)


class PlanState(Port):
    """The gears' view of the world: the approved plan, the harness's own state folder, and the git facts (GitView)."""

    def __init__(self, port, protected=DEFAULT_PROTECTED):
        self.port, self.git = port, GitView(Path(port.path).parent.parent, protected)

    def read(self, event):
        return {"plan": self.port.approved(event.session), "state_dir": str(self.port.path.parent).replace("\\", "/"),
                "git_view": self.git}
