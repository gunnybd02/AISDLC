"""Upgrade: the one door that raises a ledger's schema version (docs/12-ledger.md). A version only adds objects, so an
older ledger becomes the latest by running the blocks it lacks. It is one write transaction: the ledger has exactly an
older version's structure, the missing objects are made, user_version is set, the new fingerprint is checked, and one
pl_logs row says so; any fault rolls all of it back and the ledger stays as it was. Two openers do not both upgrade:
the second waits for the write lock and finds the latest version. Only the code in force calls it (Ledger.open with
upgrade=True, from assemble/engine/ledger_core.py)."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid

from harness.utils.ledger.db import LedgerError, blocks, fingerprint, latest, pinned, version_of


def upgrade(con: sqlite3.Connection) -> tuple[int, int]:
    """Bring an open ledger to the latest schema version, every row kept.

    Args:
        con: a connection to the ledger in autocommit mode (isolation_level None), with no transaction open.

    Returns:
        (the version it had, the version it has now); the same twice when it was the latest already.

    Raises:
        LedgerError: its structure is that of no version, or the upgraded structure is not the latest's; nothing is
            changed then.
        sqlite3.Error: a statement of a block fails; nothing is changed then.
    """
    con.execute("BEGIN IMMEDIATE")
    try:
        found = version_of(con)
        if not found:
            raise LedgerError("the ledger has the structure of no schema version: it is not upgraded")
        if found < latest():
            for version in range(found + 1, latest() + 1):
                for sql in blocks().get(version, []):
                    con.execute(sql)
            con.execute(f"PRAGMA user_version = {latest()}")
            if fingerprint(con) != pinned():
                raise LedgerError(f"the ledger upgraded from version {found} has not the structure of version {latest()}")
            con.execute("INSERT INTO pl_logs (uid, body, at) VALUES (?, ?, ?)", (uuid.uuid4().hex, json.dumps(
                {"what": "ledger-upgrade", "sid": "", "from": found, "to": latest()}), int(time.time() * 1000)))
        con.execute("COMMIT")
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    return found, latest()
