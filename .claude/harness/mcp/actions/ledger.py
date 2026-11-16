"""ledger: the one way the model reads the harness's data. The shell, Read, Grep and Glob never open state/
(read.state); a query here is one read-only SELECT, and the transcript tables (tx_*) stay out of it. export makes a
whole copy for a store outside the machine (utils/ledger/export.py) and says the one Drive call that uploads it: the
harness cannot call Drive itself, the model does."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from harness.utils.contracts import READ, WRITE, ActionContext, ActionError, McpAction
from harness.utils.git.branches import current
from harness.utils.git.facts import top
from harness.utils.ledger import store
from harness.utils.orchestra import crew
from harness.utils.ledger.export import FOLDER, FOLDER_ID, snapshot, upload_call
from harness.utils.plan.life import settle
from harness.utils.ledger.db import LedgerError, query

ACTIONS = [("ledger.db_query", "DbQuery"), ("ledger.plans_settle", "PlansSettle"), ("ledger.export", "Export"),
           ("ledger.store_status", "StoreStatus"), ("ledger.usage_backfill", "UsageBackfill"),
           ("ledger.annotate", "Annotate"), ("ledger.chain_check", "ChainCheck")]
STORE_NOTE = ("\nStore: run('ledger', 'export', {reason: 'push'}) and upload the copy as its answer says "
              "(guide('store', 'skills')).")


def store_note(ctx: ActionContext) -> str:
    """What the answer of a push or a merge request adds when a store folder is set: the ledger's copy is due.

    Args:
        ctx: the action's ports, with store (store() -> the store folder's id, or "" when none is set).

    Returns:
        STORE_NOTE (on a new line) when a store folder is set, else "".
    """
    return STORE_NOTE if ctx.ports["store"]() else ""


def where(folder: str | Path) -> dict[str, str]:
    """{repo, branch} of the folder a copy is asked from, for the copy's record; {} outside a repository.

    Args:
        folder: the folder the copy is asked from.

    Returns:
        {"repo": the repository's folder name, "branch": its current branch or ""}; {} outside a repository or when
        git cannot tell.
    """
    try:
        repo = top(folder)
        return {"repo": Path(repo).name, "branch": current(repo) or ""} if repo else {}
    except Exception:
        return {}


class DbQuery(McpAction):
    """ledger.db_query: one read-only SELECT on the ledger."""
    block, name, effect = "ledger", "db_query", READ
    summary = "Read the ledger: one SELECT, read only, at most 200 rows; writes, PRAGMA and the tx_* tables are refused"
    args_schema = {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}
    needs = ("ledger",)

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Run one read-only SELECT on the ledger; answer its rows as tab-separated lines under the column names, with a
        note when rows were cut. ActionError for a query the ledger refuses."""
        try:
            columns, rows, cut = query(ctx.ports["ledger"].path, args["sql"])
        except LedgerError as e:
            raise ActionError(str(e)) from e
        lines = ["\t".join(columns)] + ["\t".join("" if v is None else str(v) for v in row) for row in rows]
        return "\n".join(lines + (["(more rows: narrow the query)"] if cut else []))


class PlansSettle(McpAction):
    """ledger.plans_settle: the open desk plans, settled by their proof."""
    block, name, effect = "ledger", "plans_settle", WRITE
    summary = ("List the open desk plans and what proves their end; write: true ends the proven ones; drop: [plans] "
               "ends unproven plans of sessions that no longer run, after the user's Yes in a form")
    args_schema = {"type": "object", "properties": {"write": {"type": "boolean"}, "drop": {"type": "array"}},
                   "required": []}
    needs = ("plans",)

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """List the open desk plans and their proof, and end the proven ones (write) or drop unproven ones of dead
        sessions (drop) (utils/plan/life.settle); answer the list and what was done."""
        return settle(ctx.ports["plans"], bool(args.get("write")), args.get("drop"))


class UsageBackfill(McpAction):
    """ledger.usage_backfill: the token usage the transcripts hold and the ledger lacks."""
    block, name, effect = "ledger", "usage_backfill", WRITE
    summary = ("Report the token usage the transcripts on this machine hold and the ledger lacks; write: true records it "
               "once and seeds the list prices when there are none (the harness records usage by itself at each end "
               "of a turn; this is for sessions from before)")
    args_schema = {"type": "object", "properties": {"write": {"type": "boolean"}}, "required": []}
    needs = ("plans",)

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Answer what the transcripts hold that the ledger lacks, and record it when write is true."""
        return ctx.ports["plans"].usage_backfill(bool(args.get("write")))


class Annotate(McpAction):
    """ledger.annotate: one judgment of the model about a span, a turn, a session or a plan."""
    block, name, effect = "ledger", "annotate", WRITE
    summary = ("Keep one judgment of a review: unit (span, turn, session or plan), ref (which one), name and identifier "
               "(the review it belongs to), with a label, a score and a one-line explanation; the row is marked as the "
               "model's and no gate reads it")
    args_schema = {"type": "object", "properties": {
        "unit": {"type": "string"}, "ref": {"type": "string"}, "name": {"type": "string"},
        "identifier": {"type": "string"}, "label": {"type": "string"}, "score": {"type": "number"},
        "explanation": {"type": "string"}}, "required": ["unit", "ref", "name", "identifier"]}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Keep the judgment; ActionError when a field is missing or wrong (nothing is written then)."""
        problem = ctx.ports["plans"].annotate(ctx.ports["session"], args)
        if problem:
            raise ActionError(problem)
        return f"Kept: {args['name']} on {args['unit']} {args['ref']} (annotator LLM)."


class ChainCheck(McpAction):
    """ledger.chain_check: whether the ledger's hash chains are whole."""
    block, name, effect = "ledger", "chain_check", READ
    summary = ("Check the hash chains of the ledger's evidence (plans, commits, verify receipts, git audit, file grants, "
               "behaviours): each table's rows and whether its chain is whole, or the first row that breaks it")
    args_schema = {"type": "object", "properties": {}, "required": []}
    needs = ("plans",)

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Answer one line per chained table, and whether every chain is whole."""
        report = ctx.ports["plans"].chains()
        lines = [f"{table}: {rows} row(s), " + ("whole" if row is None else f"BROKEN at row {row}")
                 for table, rows, row in report]
        broken = [table for table, _, row in report if row is not None]
        end = (f"{len(broken)} chain(s) broken: a row was changed after it was written. Tell the user."
               if broken else "Every chain is whole.")
        return "\n".join(lines + [end])


class Export(McpAction):
    """ledger.export: a whole copy of the ledger for the store, and the Drive call that uploads
    it."""
    block, name, effect = "ledger", "export", WRITE
    summary = ("Copy the whole ledger for the store outside this machine (same schema as every copy; it records and is "
               "named by ledger, number, session, time, reason and commit) into .harness-export/ of the working folder "
               "(or of the folder into) and say the one Google Drive call that uploads it; reason is manual, push, "
               "plan-close, turn-end or handback; a session of an orchestra run adds its plan marker "
               "orch.<plan id>.<child or parent> to the name; refused with no store folder")
    args_schema = {"type": "object", "properties": {"folder": {"type": "string"}, "into": {"type": "string"},
                                                    "reason": {"type": "string"}}, "required": []}
    needs = ("ledger", "session", "store", "plans")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Copy the whole ledger into <into>/.harness-export/ for the store and answer the one Drive call that uploads
        it. ActionError with no store folder, into not a folder, an unknown reason, or no ledger yet."""
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
            sid = ctx.ports["session"]()
            tag = crew.store_tag(ctx.ports["plans"].ticket(sid)) if "plans" in ctx.ports and sid else ""
            record = store.begin(port, sid, reason, where(into), tag=tag)
            copy = snapshot(port.path, into / FOLDER, record)
        except LedgerError as e:
            raise ActionError(str(e)) from e
        return upload_call(copy, folder)


class StoreStatus(McpAction):
    """ledger.store_status: what the store holds and what is in no copy yet."""
    block, name, effect = "ledger", "store_status", READ
    summary = ("The store as this ledger knows it: whether a folder is set, the ledger's id, the newest copy made, the "
               "newest copy the store holds, and the work that is in no copy yet")
    needs = ("ledger",)

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Answer the store as this ledger knows it (utils/ledger/store.status)."""
        return store.status(ctx.ports["ledger"])
