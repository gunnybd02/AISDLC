"""ledger: the one way the model reads the harness's data. The shell, Read, Grep and Glob never open state/
(read.state); a query here is one read-only SELECT, and the transcript tables (tx_*) stay out of it."""
from harness.utils.contracts import READ, ActionError, McpAction
from harness.utils.ledger.db import LedgerError, query

ACTIONS = [("ledger.db_query", "DbQuery")]


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
