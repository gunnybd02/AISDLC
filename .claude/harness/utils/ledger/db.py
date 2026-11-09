"""Ledger: the private SQLite DB of the harness. A new DB is made from schema.sql, a copy of the real ledger's schema;
every open compares the DB's fingerprint with the one schema.sql gives, and a DB that drifted does not open.

The fingerprint covers every table, index, view and trigger, its name and its CREATE text with comments and runs of
spaces taken out: the same schema written another way is the same, any real change is not."""
import hashlib
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


class LedgerError(Exception):
    pass


def normal(sql):
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return " ".join(sql.split()).rstrip(";").strip()


def fingerprint(con):
    rows = con.execute("SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
                       "ORDER BY type, name").fetchall()
    text = "\n".join(f"{t}|{n}|{normal(s)}" for t, n, s in rows)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def statements():
    """The statements of schema.sql: one a line, comments left out."""
    return [line.strip().rstrip(";") for line in SCHEMA.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("--")]


@lru_cache(maxsize=1)
def pinned():
    """The fingerprint schema.sql gives."""
    con = sqlite3.connect(":memory:")
    try:
        for sql in statements():
            con.execute(sql)
        return fingerprint(con)
    finally:
        con.close()


def has_tables(con):
    return con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0] > 0


class Ledger:
    def __init__(self, path, con):
        self.path, self.con = Path(path), con

    @classmethod
    def open(cls, path):
        """Open the DB; one with no table (new, or left empty by a crash) gets the schema in one transaction, which a
        second process waits for instead of making it twice."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, isolation_level=None, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            if not has_tables(con):
                con.execute("BEGIN IMMEDIATE")
                try:
                    if not has_tables(con):
                        for sql in statements():
                            con.execute(sql)
                    con.execute("COMMIT")
                except BaseException:
                    con.execute("ROLLBACK")
                    raise
            if fingerprint(con) != pinned():
                raise LedgerError(f"{path}: its schema is not the one of schema.sql (it drifted)")
        except BaseException:
            con.close()
            raise
        return cls(path, con)

    def close(self):
        self.con.close()

    def write(self, change):
        """Run change(con) in one transaction: all of it is written, or nothing."""
        self.con.execute("BEGIN IMMEDIATE")
        try:
            result = change(self.con)
            self.con.execute("COMMIT")
        except BaseException:
            if self.con.in_transaction:
                self.con.execute("ROLLBACK")
            raise
        return result

    def all(self, sql, args=()):
        return [dict(r) for r in self.con.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None
