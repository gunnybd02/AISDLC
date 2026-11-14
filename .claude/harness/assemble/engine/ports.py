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
import json
import time
import uuid
from pathlib import Path

from harness.assemble.engine.config import Config, ConfigError
from harness.utils.contracts import YES, Port
from harness.utils.git.branches import DEFAULT_PROTECTED, current, is_protected
from harness.utils.git.facts import head, top, unpushed_files
from harness.utils.plan import grants, opening, render, request, revisions, stop, tickets
from harness.utils.plan.verify import dirty
from harness.utils.plan.desk import new_id
from harness.utils.plan.files import key, relative
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
            if sid:
                held = (json.loads(r[0]) for r in con.execute("SELECT body FROM pl_approval WHERE sid = ?", (sid,)))
                opening.approval(con, sid, {**next(held, {"open": False}), "pending": render.block(items, plan_id, rev),
                                            "pendingAge": 0, "tool": {"planId": plan_id, "rev": rev,
                                                                      "sha": revisions.newest(con, plan_id)["sha"]}})
            return rev

        rev = self.write(change)
        return plan_id, rev, question(items, plan_id, rev)

    def revision(self, plan_id):
        """The newest revision of a desk plan and its state (utils/plan/revisions.newest), or None."""
        return self.read(lambda con: revisions.newest(con, plan_id))

    def drop(self, plan_id, rev, sid):
        def change(con, rec):
            self.event(con, rec, plan_id, "dropped", rev, sid=sid)
            held = [json.loads(r[0]) for r in con.execute("SELECT body FROM pl_approval WHERE sid = ?", (sid,))]
            if held:
                opening.approval(con, sid, {**held[0], "pending": None, "tool": None})
        self.write(change)

    def feedback(self, plan_id, rev, sid, text):
        self.write(lambda con, rec: revisions.feedback(con, plan_id, rev, sid, text))

    def unread(self, plan_id, since):
        return self.read(lambda con: revisions.unread(con, plan_id, since)) or []

    @staticmethod
    def event(con, rec, plan_id, name, rev, ref=None, sid=""):
        opening.event(con, rec, plan_id, name, rev, ref, sid)

    def waiting(self):
        """The newest revision of each desk plan that waits for its approval, with its question."""
        return [{**w, "question": question(w["items"], w["plan_id"], w["rev"])}
                for w in self.read(revisions.waiting) or []]

    def approve(self, sid, waiting):
        """The user approved this waiting revision in the session sid: open it in one transaction
        (utils/plan/opening.py). base is the commit its repository stands on now, which a delivered commit must come
        from."""
        repo = top(waiting["items"]["root"])
        base = head(repo) if repo else None
        return self.write(lambda con, rec: opening.open_plan(con, rec, sid, waiting, base))

    def prompt(self, sid, text):
        """Keep the user's prompt; the plan a bare agreement word would wrongly approve, or None."""
        self.write(lambda con, rec: request.record_prompt(con, sid, text))
        if request.bare_agreement(text):
            mine = [w for w in self.waiting() if w["sid"] in (sid, "")]
            return mine[-1] if mine else None
        return None

    def approved(self, sid):
        """The plan in force in the session: the plan of its newest ticket, while that ticket holds one, with its file
        grants [(op, path from its root)] in the order they were given (pl_file_grants). None else."""
        plan = tickets.approved_plan(self.ticket(sid))
        return {**plan, "grants": self.grants(plan)} if plan else None

    def grants(self, plan):
        out = []
        for r in self.rows("SELECT op, file FROM pl_file_grants WHERE plan_id = ? ORDER BY rowid", (plan["id"],)):
            rel = relative(r["file"], plan["root"])
            if rel is not None:
                out.append((r["op"], rel.replace("\\", "/")))
        return out

    def approved_plan(self, plan_id):
        """The plan in force whose desk id is plan_id (pd-...), whatever its session; None when no open ticket holds it."""
        return tickets.approved_plan(self.read(lambda con: tickets.open_with_draft(con, plan_id)))

    def protected(self, branch):
        """Whether the branch is protected (project.json protected; main and master when it cannot be read)."""
        try:
            patterns = Config.load(self.path.parent.parent).protected
        except ConfigError:
            patterns = DEFAULT_PROTECTED
        return is_protected(branch, patterns)

    def registry(self, plan):
        """The behaviour registry of the plan (utils/plan/grants.replay), from pl_behaviors in the order written."""
        ids = sorted({plan["id"], plan.get("rootId", plan["id"])})
        rows = self.rows(f"SELECT op, id, entry FROM pl_behaviors WHERE plan_id IN ({', '.join('?' * len(ids))}) "
                         "ORDER BY rowid", ids)
        return grants.replay([(r["op"], r["id"], r["entry"]) for r in rows])

    def changed_files(self, plan):
        return dirty(plan)

    def door(self, sid, plan, grants=(), behaviors=()):
        """The rows of one CLI door, in one transaction: file grants (op, absolute path, why) and behaviour rows
        (op, id, entry), all chained."""
        def change(con, rec):
            for op, path, why in grants:
                rec.insert(con, "pl_file_grants", {"uid": uuid.uuid4().hex, "sid": sid, "plan_id": plan["id"],
                                                   "op": op, "file": path, "why": why, "at": now()})
            for op, bid, entry in behaviors:
                rec.insert(con, "pl_behaviors", {"uid": uuid.uuid4().hex, "sid": sid, "plan_id": plan["id"],
                                                 "repo": plan["root"], "op": op, "id": bid,
                                                 "entry": json.dumps(entry, ensure_ascii=False), "at": now()})
        self.write(change)

    def step_commit(self, sid, ticket, plan, repo, sha, fixing):
        """The step's commit is made: keep it; the ticket moves on (after the last step: deliver, and a home plan
        closes delivered with no form). A fix keeps the ticket in deliver. One transaction; the ticket after."""
        def change(con, rec):
            rec.insert(con, "rec_commits", {"plan_id": plan["id"], "service": repo, "commit_sha": sha, "at": now(),
                                            "uid": uuid.uuid4().hex})
            fresh = tickets.latest(con, sid)
            done = {**fresh, "commits": fresh["commits"] + [sha],
                    "stepCommits": {**fresh.get("stepCommits", {}),
                                    str(fresh["step"]): fresh.get("stepCommits", {}).get(str(fresh["step"]), []) + [sha]}}
            done = {**done, "phase": "deliver"} if fixing else tickets.move(done)
            if not fixing and done["phase"] == "deliver" and not plan.get("children"):  # close_home
                done = {**done, "state": tickets.CLOSED, "closeReason": tickets.DELIVERED}
                self.event(con, rec, plan["plan_id"], "delivered", plan["rev"], plan["id"], sid)
            return tickets.save(con, done)
        return self.write(change)

    def step_skip(self, sid, ticket, plan, ids, why):
        def change(con, rec):
            for bid in ids:
                rec.insert(con, "pl_behaviors", {"uid": uuid.uuid4().hex, "sid": sid, "plan_id": plan["id"],
                                                 "repo": plan["root"], "op": "skip", "id": bid,
                                                 "entry": json.dumps({"why": why}, ensure_ascii=False), "at": now()})
            fresh = tickets.latest(con, sid)
            return tickets.save(con, tickets.move({**fresh, "skips": fresh.get("skips", 0) + 1}))
        return self.write(change)

    def close_plan(self, sid, ticket, reason, facts):
        """The user closed the ticket's plan in the close form (delivered or abandoned): one transaction closes the
        ticket, ends the approval, writes the event (delivered, dropped) and keeps the facts the user saw."""
        def change(con, rec):
            fresh = tickets.latest(con, sid)
            tickets.close(con, fresh, reason)
            held = [json.loads(r[0]) for r in con.execute("SELECT body FROM pl_approval WHERE sid = ?", (sid,))]
            opening.approval(con, sid, {**(held[0] if held else {}), "open": False})
            plan = fresh["plan"]
            self.event(con, rec, plan["plan_id"], "delivered" if reason == "delivered" else "dropped", plan["rev"],
                       plan["id"], sid)
            opening.log(con, sid, "closure", ticket=fresh["id"], plan=plan["id"], reason=reason, facts=facts)
        self.write(change)

    def holder(self, plan_id):
        """The newest ticket that holds the desk plan plan_id, open or closed, or None."""
        for r in self.rows("SELECT body FROM pl_tickets ORDER BY at DESC, seq DESC"):
            body = json.loads(r["body"])
            if body.get("draft") == plan_id:
                return body
        return None

    def end_plan(self, plan, how, abandon=False):
        """plans_settle ends a desk plan: its event (delivered or dropped); with abandon, its open ticket closes."""
        def change(con, rec):
            if abandon:
                holder = next((json.loads(r[0]) for r in con.execute(
                    "SELECT body FROM pl_tickets WHERE state = 'open' ORDER BY seq DESC") if json.loads(r[0]).get("draft")
                               == plan["plan_id"]), None)
                if holder:
                    tickets.close(con, holder, tickets.ABANDONED)
            self.event(con, rec, plan["plan_id"], how, plan["rev"], plan.get("ref"), plan["sid"])
        self.write(change)

    def back(self, sid):
        """A write to a plan file while the ticket is in deliver sends it back to execute."""
        def change(con, rec):
            fresh = tickets.latest(con, sid)
            if fresh and tickets.approved_plan(fresh) and fresh["phase"] == "deliver":
                tickets.save(con, tickets.back_to_execute(fresh))
        self.write(change)

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

    def green_receipt(self, plan):
        """The newest green receipt of the plan, or None."""
        row = next(iter(self.rows("SELECT files FROM pl_verify WHERE plan_id = ? AND ok = 1 ORDER BY at DESC, rowid DESC "
                                  "LIMIT 1", (plan["id"],))), None)
        return {"ok": 1, "files": json.loads(row["files"])} if row else None

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
                "git_view": self.git, "stop_owed": lambda plan: stop.unverified(self.port, plan)}
