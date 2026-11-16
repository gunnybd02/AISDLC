"""Recorder: rows into the ledger, inside a transaction of Ledger.write. A row names only columns of its table. A row
of a chained table carries prev_hash (the hash of the row before it) and hash (of every column of the row, its id
too, and prev_hash), so a row changed later, or given another id, breaks the chain and chain_ok() says so. A row
taken off the end of a chain is not seen this way: the chain proves no row was changed, not that none is missing."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from harness.utils.ledger.db import Ledger, LedgerError
from harness.utils.shapes import Row

CHAINED = ("rec_plans", "rec_commits", "pl_verify", "pl_git_audit", "pl_file_grants", "pl_behaviors")
CHAIN = ("prev_hash", "hash")
AUTO = {"rec_plans": "id"}  # an INTEGER PRIMARY KEY the recorder gives itself, so the hash covers it


def digest(prev: str, row: Row) -> str:
    """The hash of a chained row: sha256 of the hash before it and the row's columns as sorted JSON.

    Args:
        prev: the hash of the row before it ("" for the first row).
        row: the row by column name; its prev_hash and hash columns are left out of the hash.

    Returns:
        The hex sha256.
    """
    body = {k: v for k, v in row.items() if k not in CHAIN}
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode("utf-8")).hexdigest()


class Recorder:
    """Inserts rows into the ledger inside one transaction of Ledger.write, chaining the rows of CHAINED tables."""

    def __init__(self, ledger: Ledger) -> None:
        """Keep the ledger the rows go into.

        Args:
            ledger: the open ledger.
        """
        self.ledger = ledger

    @staticmethod
    def columns(con: sqlite3.Connection, table: str) -> list[str]:
        """The columns of a table, in their order.

        Args:
            con: the connection of the transaction.
            table: the table's name.

        Returns:
            The column names.

        Raises:
            LedgerError: the ledger has no such table.
        """
        cols = [r[1] for r in con.execute("SELECT * FROM pragma_table_info(?)", (table,)).fetchall()]
        if not cols:
            raise LedgerError(f"no table {table} in the ledger")
        return cols

    @staticmethod
    def next_id(con: sqlite3.Connection, table: str, column: str) -> int:
        """The next INTEGER PRIMARY KEY of a table, past both its AUTOINCREMENT sequence and its highest value.

        Args:
            con: the connection of the transaction.
            table: the table's name.
            column: its key column.

        Returns:
            The id the next row gets.
        """
        seq = con.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
        top = con.execute(f"SELECT MAX({column}) FROM {table}").fetchone()[0]
        return max(seq[0] if seq else 0, top or 0) + 1

    def insert(self, con: sqlite3.Connection, table: str, row: dict[str, Any]) -> int:
        """Insert one row; a chained table's id and chain columns are filled here. Returns the new rowid.

        Args:
            con: the connection of the transaction.
            table: the table's name.
            row: the values by column name; a chained table's missing columns are written as NULL.

        Returns:
            The rowid of the new row.

        Raises:
            LedgerError: the table does not exist or has no column the row names.
        """
        cols = Recorder.columns(con, table)
        unknown = sorted(set(row) - set(cols))
        if unknown:
            raise LedgerError(f"{table} has no column {', '.join(unknown)}")
        row = dict(row)
        if table in CHAINED:  # every column named, so the hash reads the row as the ledger will give it back
            row = {c: row.get(c) for c in cols if c not in CHAIN}
            if table in AUTO:
                row[AUTO[table]] = Recorder.next_id(con, table, AUTO[table])
            last = con.execute(f"SELECT hash FROM {table} ORDER BY rowid DESC LIMIT 1").fetchone()
            row["prev_hash"] = last[0] if last else ""
            row["hash"] = digest(row["prev_hash"], row)
        names = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        return con.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(row.values())).lastrowid

    @staticmethod
    def chain_ok(ledger: Ledger, table: str) -> bool:
        """Whether every row of a chained table holds the hash of the row before it and its own right hash.

        Args:
            ledger: the open ledger.
            table: a table of CHAINED.

        Returns:
            True when the chain is whole (an empty table too).
        """
        prev = ""
        for row in ledger.all(f"SELECT * FROM {table} ORDER BY rowid"):
            if row["prev_hash"] != prev or row["hash"] != digest(prev, row):
                return False
            prev = row["hash"]
        return True
