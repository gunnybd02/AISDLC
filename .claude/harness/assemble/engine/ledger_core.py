"""The ledger's plumbing under LedgerPort (ports.py): where the ledger is (state/harness.db), one transaction for a
write, the rows of a read, and the event row of a desk plan. Reading never creates the ledger; the ledger is opened
at its first write or read once it exists. DeskPort (desk_port.py) and TicketPort (ticket_port.py) build on it."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Callable, Optional, TypeVar

from harness.utils.plan import opening
from harness.utils.ledger.db import Ledger
from harness.utils.ledger.recorder import Recorder
from harness.utils.shapes import Change, Row

T = TypeVar("T")


def now() -> int:
    """The time now, in milliseconds since the epoch (the `at` of every row the port writes).

    Returns:
        The current time in ms.
    """
    return int(time.time() * 1000)


class LedgerCore:
    """The ledger of a home: its path, the open ledger, and the plain read and write every port method goes through."""

    def __init__(self, claude_dir: str | Path) -> None:
        """Name the ledger of the home; nothing is opened or created yet.

        Args:
            claude_dir: the home, the .claude folder whose state/harness.db is the ledger.
        """
        self.path = Path(claude_dir) / "state" / "harness.db"
        self._ledger = None

    @property
    def ledger(self) -> Ledger:
        """The open ledger, opened (and made from schema.sql when new) at the first use.

        Returns:
            The Ledger of state/harness.db.
        """
        if self._ledger is None:
            self._ledger = Ledger.open(self.path)
        return self._ledger

    def write(self, change: Change[T]) -> T:
        """Run change(con, rec) in one transaction and give back what it returns.

        Args:
            change: change(con, rec) -> T; rec (a Recorder) inserts rows, chained ones too.

        Returns:
            What change returned.
        """
        return self.ledger.write(lambda con: change(con, Recorder(self.ledger)))

    def rows(self, sql: str, args: tuple | list = ()) -> list[Row]:
        """The rows of one read query; [] when there is no ledger yet (a read never makes one).

        Args:
            sql: the query, with ? placeholders.
            args: the values of the placeholders.

        Returns:
            Each row as {column: value}.
        """
        return self.ledger.all(sql, args) if self.path.exists() else []

    def read(self, look: Callable[[sqlite3.Connection], T]) -> Optional[T]:
        """look(con) on the ledger, or None when there is no ledger yet (a read never makes one).

        Args:
            look: look(con) -> T, a read on the ledger's connection.

        Returns:
            What look returned, or None with no ledger.
        """
        return look(self.ledger.con) if self.path.exists() else None

    @staticmethod
    def event(con: sqlite3.Connection, rec: Recorder, plan_id: str, name: str, rev: int, ref: Optional[int] = None,
              sid: str = "") -> None:
        """Write one event of a desk plan (pl_plan_events, utils/plan/opening.event) inside a write.

        Args:
            con: the connection of the running transaction.
            rec: the recorder of that transaction.
            plan_id: the desk id (pd-...).
            name: the event: waiting, dropped, approved, executing, delivered.
            rev: the revision it is for.
            ref: the plan number in rec_plans it concerns, or None.
            sid: the session it happened in ("" when none).
        """
        opening.event(con, rec, plan_id, name, rev, ref, sid)
