"""Ports: what a run reads from outside and writes back.

LedgerPort keeps the plans of the harness in the ledger (state/harness.db):
- present: a revision of a plan, waiting (pl_plan_revs, a 'waiting' event);
- approve: the user's "Duyệt" in the form to that revision's question (a chained rec_plans row, an 'approved' event);
- approved: the plan a session works under, the newest it approved, until it is delivered.
A row is never changed after it is written: the state of a plan is its events. Reading never creates the ledger.

PlanState gives the approved plan of the event's session as a fact, for the gears."""
import hashlib
import json
import secrets
import time
import uuid
from pathlib import Path

from harness.utils.contracts import Port
from harness.utils.ledger.db import Ledger
from harness.utils.ledger.recorder import Recorder

YES = "Duyệt"
HEAD = "Duyệt plan "


def question(title, plan_id, rev):
    return f'{HEAD}"{title}" ({plan_id} rev {rev})?'


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

    def present(self, items, plan_id=None):
        """Keep a revision of a plan; give (plan id, revision, the form question)."""
        plan_id = plan_id or f"pd-{secrets.token_hex(4)}"
        body = json.dumps(items, sort_keys=True, ensure_ascii=False)

        def change(con, rec):
            rev = 1 + (con.execute("SELECT MAX(rev) FROM pl_plan_revs WHERE plan_id = ?", (plan_id,)).fetchone()[0] or 0)
            rec.insert(con, "pl_plan_revs", {"plan_id": plan_id, "rev": rev, "sid": "", "items": body, "why": "",
                                              "sha": hashlib.sha256(body.encode()).hexdigest()[:8], "at": now()})
            self.event(con, rec, plan_id, "waiting", rev)
            return rev

        rev = self.write(change)
        return plan_id, rev, question(items["title"], plan_id, rev)

    @staticmethod
    def event(con, rec, plan_id, name, rev, ref=None, sid=""):
        n = 1 + (con.execute("SELECT MAX(n) FROM pl_plan_events WHERE plan_id = ?", (plan_id,)).fetchone()[0] or 0)
        rec.insert(con, "pl_plan_events", {"plan_id": plan_id, "n": n, "sid": sid, "event": name, "rev": rev,
                                           "ref": ref, "at": now()})

    def waiting(self):
        """The newest revision of each plan whose newest revision is not approved, with its question."""
        out = []
        for r in self.rows("SELECT r.plan_id, r.rev, r.items FROM pl_plan_revs r WHERE r.rev = (SELECT MAX(x.rev) FROM "
                           "pl_plan_revs x WHERE x.plan_id = r.plan_id) AND NOT EXISTS (SELECT 1 FROM pl_plan_events e "
                           "WHERE e.plan_id = r.plan_id AND e.rev = r.rev AND e.event = 'approved') ORDER BY r.at"):
            items = json.loads(r["items"])
            out.append({"plan_id": r["plan_id"], "rev": r["rev"], "items": items,
                        "question": question(items["title"], r["plan_id"], r["rev"])})
        return out

    def approve(self, sid, waiting, root):
        """The user approved this waiting revision in the session sid, whose work is under root."""
        scope = {"plan_id": waiting["plan_id"], "rev": waiting["rev"], "root": root, **waiting["items"]}

        def change(con, rec):
            rid = rec.insert(con, "rec_plans", {"sid": sid, "sha": hashlib.sha256(json.dumps(scope, sort_keys=True)
                                                                                   .encode()).hexdigest()[:8],
                                                "reason": "form", "scope": json.dumps(scope, ensure_ascii=False),
                                                "services": "[]", "status": "approved", "at": now(),
                                                "uid": uuid.uuid4().hex})
            self.event(con, rec, waiting["plan_id"], "approved", waiting["rev"], rid, sid)
            return rid

        return self.write(change)

    def approved(self, sid):
        """The plan the session works under: its newest approval, unless that plan was delivered. None if there is none."""
        row = next(iter(self.rows("SELECT id, scope FROM rec_plans WHERE sid = ? ORDER BY id DESC LIMIT 1", (sid,))), None)
        if row is None or self.rows("SELECT 1 FROM pl_plan_events WHERE event = 'delivered' AND ref = ?", (row["id"],)):
            return None
        return {"id": row["id"], **json.loads(row["scope"])}

    def decision(self, event, plan, finding, verdict):
        self.write(lambda con, rec: rec.insert(con, "act_rule_decisions", {
            "uid": uuid.uuid4().hex, "sid": event.session, "agent": "", "plan_id": plan["id"] if plan else None,
            "rule": finding.kind, "kind": "finding", "tool": event.tool, "service": "", "verdict": verdict,
            "detail": finding.detail, "at": now()}))


class PlanState(Port):
    def __init__(self, port):
        self.port = port

    def read(self, event):
        return {"plan": self.port.approved(event.session)}
