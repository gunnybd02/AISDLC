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


def objects(con):
    """{(type, name): CREATE text, normalised} of every table, index, view and trigger."""
    rows = con.execute("SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")
    return {(t, n): normal(s) for t, n, s in rows.fetchall()}


def fingerprint(con):
    text = "\n".join(f"{t}|{n}|{s}" for (t, n), s in sorted(objects(con).items()))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def statements():
    """The statements of schema.sql: one a line, comments left out."""
    return [line.strip().rstrip(";") for line in SCHEMA.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("--")]


def in_memory():
    """A DB in memory with the schema of schema.sql."""
    con = sqlite3.connect(":memory:")
    for sql in statements():
        con.execute(sql)
    return con


@lru_cache(maxsize=1)
def pinned():
    """The fingerprint schema.sql gives."""
    con = in_memory()
    try:
        return fingerprint(con)
    finally:
        con.close()


def drift(theirs, ours):
    """One line per object that is not the same in both: missing, extra, or with another CREATE text."""
    out = []
    for key in sorted(set(theirs) | set(ours)):
        what = f"{key[0]} {key[1]}"
        if key not in theirs:
            out.append(f"{what} is missing")
        elif key not in ours:
            out.append(f"{what} is not in schema.sql")
        elif theirs[key] != ours[key]:
            out.append(f"{what} differs")
    return out


def compare_real(path):
    """The problems of the real ledger at path against schema.sql, one line each; [] when its schema is the same.
    It is opened read only (mode=ro) and never written. At rest (no -wal, no -journal) it is read as immutable, so no
    file is made beside it, and a -wal or -journal still there after the read makes the read void (a writer that starts
    and ends within the read leaves no trace: this is best effort, not a lock). In use, it is read through its own -wal
    and -shm; only the -shm, the shared index of the readers, may change. A ledger whose schema cannot be read is a
    problem, never a match: no such file, an empty file, not a database, a -wal without its -shm (a reader cannot
    rebuild the index), or a journal a read-only reader cannot roll back."""
    path = Path(path)
    side = [path.with_name(path.name + end) for end in ("-wal", "-journal")]
    if not path.is_file():
        return [f"{path}: no such file; its schema is not compared"]
    if path.stat().st_size == 0:
        return [f"{path}: an empty file; its schema is not compared"]
    if side[0].exists() and not path.with_name(path.name + "-shm").exists():
        return [f"{path}: a -wal file without its -shm; its schema is not compared"]
    at_rest = not any(p.exists() for p in side)
    try:
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro{'&immutable=1' if at_rest else ''}", uri=True)
        try:
            theirs = objects(con)
        finally:
            con.close()
        if at_rest and any(p.exists() for p in side):
            return [f"{path}: it was written to while being read; its schema is not compared"]
        ours = in_memory()
        try:
            return [f"{path}: {line}" for line in drift(theirs, objects(ours))]
        finally:
            ours.close()
    except sqlite3.Error as e:
        return [f"{path}: cannot be read read only ({e}); its schema is not compared"]


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


HIDDEN = ("tx_",)  # transcripts: kept in the ledger, never read by a query
ROWS = 200


def query(path, sql, limit=ROWS):
    """(columns, rows, cut) of one SELECT on the ledger at path, opened read only. An authorizer lets through reads
    and functions only: a write, a PRAGMA, an ATTACH or a read of a hidden table (tx_*) is refused before it runs;
    sqlite3 itself refuses a second statement."""
    path = Path(path)
    if not path.is_file():
        raise LedgerError("the ledger has no data yet")
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}

    def authorize(action, arg1, arg2, db, trigger):
        if action == sqlite3.SQLITE_READ:
            return sqlite3.SQLITE_DENY if str(arg1).lower().startswith(HIDDEN) else sqlite3.SQLITE_OK
        return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY

    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
    try:
        con.set_authorizer(authorize)
        cur = con.execute(sql)
        columns = [d[0] for d in cur.description or ()]
        rows = cur.fetchmany(limit + 1)
    except (sqlite3.Error, ValueError) as e:
        raise LedgerError(f"the query is refused or wrong: {e}") from e
    finally:
        con.close()
    return columns, rows[:limit], len(rows) > limit
