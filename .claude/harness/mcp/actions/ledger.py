"""ledger: the one way the model reads the harness's data. The shell, Read, Grep and Glob never open state/
(read.state); a query here is one read-only SELECT, and the transcript tables (tx_*) stay out of it."""
from harness.mcp.actions.table import McpAction
from harness.utils.ledger.db import query

BLOCK = "ledger"
ABOUT = "Read the harness's ledger: one read-only SELECT; transcripts (tx_*) are never read"


class DbQuery(McpAction):
    name = "db_query"
    about = "One SELECT on the ledger, read only, at most 200 rows; writes, PRAGMA and the tx_* tables are refused"
    args = {"sql": "string"}
    needs = ("ledger",)

    def __call__(self, sql):
        columns, rows, cut = query(self.ports["ledger"].path, sql)
        lines = ["\t".join(columns)] + ["\t".join("" if v is None else str(v) for v in row) for row in rows]
        return "\n".join(lines + (["(more rows: narrow the query)"] if cut else []))


ACTIONS = [DbQuery]
