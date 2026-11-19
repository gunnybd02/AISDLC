"""Join: one memory from many ledger copies (docs/system.md section 9, part 7). Each session's ledger records itself and
its copies go to Drive db/ (export.py); join takes copies (gzipped or plain, as downloaded) and merges their rows into
MEMORY, a database of the same schema beside the ledger, never the ledger itself:

- a copy whose schema is not the pinned one (schema.sql) is refused, so every row reads the same way;
- a row is taken once, by its uid where its table has one, else by its primary key, else by its whole value; a row
  whose key another copy's row already holds is counted as a clash, never written over;
- the transcripts (tx_*) are not joined: no query reads them;
- COPIES, a table of the memory only, keeps each joined copy (name, sha256, rows taken, when).
ledger db_query with memory true reads it, read only, as it reads the ledger."""
from __future__ import annotations

import gzip
import hashlib
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from harness.utils.ledger.db import HIDDEN, LedgerError, fingerprint, pinned, statements

MEMORY = "memory.db"
COPIES = "mem_copies"


def memory_of(ledger: str | Path) -> Path:
    """The memory's file: MEMORY beside the ledger."""
    return Path(ledger).with_name(MEMORY)


def opened(memory: Path) -> sqlite3.Connection:
    """The memory, made with the pinned schema and COPIES the first time."""
    fresh = not memory.is_file()
    con = sqlite3.connect(memory, timeout=10)
    if fresh:
        for sql in statements():
            con.execute(sql)
        con.execute(f"CREATE TABLE {COPIES} (name TEXT, sha256 TEXT PRIMARY KEY, rows INTEGER, clashes INTEGER, "
                    "at INTEGER)")
        con.commit()
    return con


def plain_copy(path: Path, folder: Path) -> Path:
    """The copy as an SQLite file: a .gz copy is unpacked into folder."""
    if path.suffix != ".gz":
        return path
    out = folder / path.with_suffix("").name
    with gzip.open(path, "rb") as packed, open(out, "wb") as raw:
        shutil.copyfileobj(packed, raw)
    return out


def tables(con: sqlite3.Connection, schema: str = "main") -> dict[str, list[tuple[str, int]]]:
    """{table: [(column, pk position)]} of a database, the transcripts and SQLite's own tables left out."""
    names = [r[0] for r in con.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type = 'table'")]
    return {t: [(r[1], r[5]) for r in con.execute(f"PRAGMA {schema}.table_info({t})")]
            for t in names if not t.startswith(HIDDEN) and not t.startswith("sqlite_")}


def take(con: sqlite3.Connection, table: str, columns: list[tuple[str, int]]) -> tuple[int, int]:
    """Copy the rows of copy.<table> the memory does not hold yet. Returns (rows taken, clashes)."""
    names = ", ".join(f'"{c}"' for c, _ in columns)
    keys = [c for c, pk in sorted(columns, key=lambda c: c[1]) if pk]
    if "uid" in [c for c, _ in columns]:
        new = f'FROM copy."{table}" AS c WHERE c.uid IS NULL OR c.uid NOT IN (SELECT uid FROM main."{table}" ' \
              'WHERE uid IS NOT NULL)'
    elif keys:
        match = " AND ".join(f'm."{k}" IS c."{k}"' for k in keys)
        new = f'FROM copy."{table}" AS c WHERE NOT EXISTS (SELECT 1 FROM main."{table}" AS m WHERE {match})'
    else:
        before = con.execute(f'SELECT count(*) FROM main."{table}"').fetchone()[0]
        con.execute(f'INSERT INTO main."{table}" ({names}) SELECT {names} FROM copy."{table}" '
                    f'EXCEPT SELECT {names} FROM main."{table}"')
        return con.execute(f'SELECT count(*) FROM main."{table}"').fetchone()[0] - before, 0
    wanted = con.execute(f"SELECT count(*) {new}").fetchone()[0]
    before = con.execute(f'SELECT count(*) FROM main."{table}"').fetchone()[0]
    picked = ", ".join(f'c."{c}"' for c, _ in columns)
    con.execute(f'INSERT OR IGNORE INTO main."{table}" ({names}) SELECT {picked} {new}')
    taken = con.execute(f'SELECT count(*) FROM main."{table}"').fetchone()[0] - before
    return taken, wanted - taken


def join(ledger: str | Path, files: list[str]) -> list[str]:
    """Merge each copy into the memory beside the ledger.

    Args:
        ledger: the ledger's file (the memory goes beside it).
        files: the copies, as downloaded (.db or .db.gz).

    Returns:
        One line per copy: rows taken and clashes, already joined, or why it was refused.
    """
    memory, lines = memory_of(ledger), []
    con = opened(memory)
    try:
        with tempfile.TemporaryDirectory() as folder:
            for name in files:
                lines.append(one(con, Path(name), Path(folder)))
    finally:
        con.close()
    return lines


def one(con: sqlite3.Connection, path: Path, folder: Path) -> str:
    """Join one copy into the open memory; the line for it."""
    if not path.is_file():
        return f"{path.name}: no such file"
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if con.execute(f"SELECT 1 FROM {COPIES} WHERE sha256 = ?", (sha,)).fetchone():
        return f"{path.name}: joined already"
    try:
        source = plain_copy(path, folder)
        check = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
        try:
            same = fingerprint(check) == pinned()
        finally:
            check.close()
    except (OSError, EOFError, sqlite3.Error) as e:
        return f"{path.name}: refused, it is no ledger copy ({type(e).__name__})"
    if not same:
        return f"{path.name}: refused, its schema is not the harness's (export it with the release in force)"
    con.execute("ATTACH DATABASE ? AS copy", (str(source),))
    try:
        taken = clashes = 0
        for table, columns in tables(con, "copy").items():
            got, clashed = take(con, table, columns)
            taken, clashes = taken + got, clashes + clashed
        con.execute(f"INSERT INTO {COPIES} (name, sha256, rows, clashes, at) VALUES (?, ?, ?, ?, ?)",
                    (path.name, sha, taken, clashes, int(time.time() * 1000)))
        con.commit()
    except sqlite3.Error as e:
        con.rollback()
        raise LedgerError(f"{path.name} could not be joined: {e}") from e
    finally:
        con.execute("DETACH DATABASE copy")
    return f"{path.name}: {taken} rows taken" + (f", {clashes} clashed with rows of another copy" if clashes else "")

