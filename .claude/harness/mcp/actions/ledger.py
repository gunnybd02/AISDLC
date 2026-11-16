"""ledger: the one way the model reads the harness's data. The shell, Read, Grep and Glob never open state/
(read.state); a query here is one read-only SELECT, and the transcript tables (tx_*) stay out of it. export makes a
whole copy for a store outside the machine (utils/ledger/export.py) and says the one Drive call that uploads it: the
harness cannot call Drive itself, the model does."""
import os
from pathlib import Path

from harness.utils.contracts import READ, WRITE, ActionError, McpAction
from harness.utils.git.branches import current
from harness.utils.git.facts import top
from harness.utils.ledger import store
from harness.utils.ledger.export import FOLDER, FOLDER_ID, snapshot, upload_call
from harness.utils.plan.life import settle
from harness.utils.ledger.db import LedgerError, query

ACTIONS = [("ledger.db_query", "DbQuery"), ("ledger.plans_settle", "PlansSettle"), ("ledger.export", "Export"),
           ("ledger.store_status", "StoreStatus")]
STORE_NOTE = ("\nStore: run('ledger', 'export', {reason: 'push'}) and upload the copy as its answer says "
              "(guide('store', 'skills')).")


def store_note(ctx):
    """What the answer of a push or a merge request adds when a store folder is set: the ledger's copy is due."""
    return STORE_NOTE if ctx.ports["store"]() else ""


def where(folder):
    """{repo, branch} of the folder a copy is asked from, for the copy's record; {} outside a repository."""
    try:
        repo = top(folder)
        return {"repo": Path(repo).name, "branch": current(repo) or ""} if repo else {}
    except Exception:
        return {}


class DbQuery(McpAction):
    block, name, effect = "ledger", "db_query", READ
    summary = "Read the ledger: one SELECT, read only, at most 200 rows; writes, PRAGMA and the tx_* tables are refused"
    args_schema = {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}
    needs = ("ledger",)

    def run(self, ctx, args):
        try:
            columns, rows, cut = query(ctx.ports["ledger"].path, args["sql"])
        except LedgerError as e:
            raise ActionError(str(e)) from e
        lines = ["\t".join(columns)] + ["\t".join("" if v is None else str(v) for v in row) for row in rows]
        return "\n".join(lines + (["(more rows: narrow the query)"] if cut else []))


class PlansSettle(McpAction):
    block, name, effect = "ledger", "plans_settle", WRITE
    summary = ("List the open desk plans and what proves their end; write: true ends the proven ones; drop: [plans] "
               "ends unproven plans of sessions that no longer run, after the user's Yes in a form")
    args_schema = {"type": "object", "properties": {"write": {"type": "boolean"}, "drop": {"type": "array"}},
                   "required": []}
    needs = ("plans",)

    def run(self, ctx, args):
        return settle(ctx.ports["plans"], bool(args.get("write")), args.get("drop"))


class Export(McpAction):
    block, name, effect = "ledger", "export", WRITE
    summary = ("Copy the whole ledger for the store outside this machine (same schema as every copy; it records and is "
               "named by ledger, number, session, time, reason and commit) into .harness-export/ of the working folder "
               "(or of the folder into) and say the one Google Drive call that uploads it; reason is manual, push, "
               "plan-close or turn-end; refused with no store folder")
    args_schema = {"type": "object", "properties": {"folder": {"type": "string"}, "into": {"type": "string"},
                                                    "reason": {"type": "string"}}, "required": []}
    needs = ("ledger", "session", "store")

    def run(self, ctx, args):
        folder = str(args.get("folder") or ctx.ports["store"]() or "").strip()
        if not FOLDER_ID.match(folder):
            raise ActionError("no store folder: the environment variable HARNESS_DRIVE_FOLDER holds the id of the "
                              "Google Drive folder (or pass {folder: '<id>'}); ask the user for it")
        into = Path(str(args.get("into") or os.getcwd()))  # the Drive tool reads only from a session's own folders
        if not into.is_dir():
            raise ActionError(f"into is a folder of this session's working folder; {into} is not a folder")
        reason = str(args.get("reason") or store.REASONS[0])
        if reason not in store.REASONS:
            raise ActionError(f"reason is one of {', '.join(store.REASONS)}")
        port = ctx.ports["ledger"]
        if not port.path.is_file():
            raise ActionError("there is no ledger yet: nothing to export")
        try:
            record = store.begin(port, ctx.ports["session"](), reason, where(into))
            copy = snapshot(port.path, into / FOLDER, record)
        except LedgerError as e:
            raise ActionError(str(e)) from e
        return upload_call(copy, folder)


class StoreStatus(McpAction):
    block, name, effect = "ledger", "store_status", READ
    summary = ("The store as this ledger knows it: whether a folder is set, the ledger's id, the newest copy made, the "
               "newest copy the store holds, and the work that is in no copy yet")
    needs = ("ledger",)

    def run(self, ctx, args):
        return store.status(ctx.ports["ledger"])
