"""Recorder: rows into the ledger, inside a transaction of Ledger.write. A row names only columns of its table. A row
of a chained table carries prev_hash (the hash of the row before it) and hash (of itself and prev_hash), so a row
changed later breaks the chain and chain_ok() says so."""
import hashlib
import json

from harness.utils.ledger.db import LedgerError

CHAINED = ("rec_plans", "rec_commits", "pl_verify", "pl_git_audit", "pl_file_grants", "pl_behaviors")
CHAIN = ("prev_hash", "hash")
AUTO = {"rec_plans": "id"}  # the row id SQLite gives: the chain does not cover it


def skipped(table):
    return CHAIN + ((AUTO[table],) if table in AUTO else ())


def digest(table, prev, row):
    body = {k: v for k, v in row.items() if k not in skipped(table)}
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode("utf-8")).hexdigest()


class Recorder:
    def __init__(self, ledger):
        self.ledger = ledger

    @staticmethod
    def columns(con, table):
        cols = [r[1] for r in con.execute("SELECT * FROM pragma_table_info(?)", (table,)).fetchall()]
        if not cols:
            raise LedgerError(f"no table {table} in the ledger")
        return cols

    def insert(self, con, table, row):
        """Insert one row; the chain columns of a chained table are filled here. Returns the new rowid."""
        cols = Recorder.columns(con, table)
        unknown = sorted(set(row) - set(cols))
        if unknown:
            raise LedgerError(f"{table} has no column {', '.join(unknown)}")
        row = dict(row)
        if table in CHAINED:  # every column named, so the hash reads the row as the ledger will give it back
            row = {c: row.get(c) for c in cols if c not in skipped(table)}
            last = con.execute(f"SELECT hash FROM {table} ORDER BY rowid DESC LIMIT 1").fetchone()
            row["prev_hash"] = last[0] if last else ""
            row["hash"] = digest(table, row["prev_hash"], row)
        names = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        return con.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(row.values())).lastrowid

    @staticmethod
    def chain_ok(ledger, table):
        prev = ""
        for row in ledger.all(f"SELECT * FROM {table} ORDER BY rowid"):
            if row["prev_hash"] != prev or row["hash"] != digest(table, prev, row):
                return False
            prev = row["hash"]
        return True
