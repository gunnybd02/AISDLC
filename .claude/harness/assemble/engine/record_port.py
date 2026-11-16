"""RecordPort: the part of the ledger port that records what a session does, by itself (docs/12-ledger.md): the
rows of utils/ledger/activity.py, each call in one transaction. A recording fault never blocks or changes a call: it
leaves one line on the error stream and the call goes on."""
from __future__ import annotations

import sys
from typing import Any, Callable, Optional

from harness.assemble.engine.ledger_core import LedgerCore
from harness.utils.contracts import CLAUDE_DECISION, Event, Verdict
from harness.utils.ledger import activity
from harness.utils.shapes import ApprovedPlan, Change

NOT_RECORDED = "harness: not recorded in the ledger ({what}): {error}\n"


class RecordPort(LedgerCore):
    """The recording of a session's actions: hook calls, runs of harness actions, the end of a turn."""

    def recorded(self, what: str, change: Change[Any]) -> None:
        """Run a recording in one transaction; a fault is told on the error stream and goes no further.

        Args:
            what: what is recorded, for the line a fault leaves.
            change: change(con, rec) makes the rows.
        """
        try:
            self.write(change)
        except Exception as e:  # recording never blocks or changes a call
            sys.stderr.write(NOT_RECORDED.format(what=what, error=f"{type(e).__name__}: {e}"))

    def record(self, event: Event, plan: Optional[ApprovedPlan], verdict: Verdict) -> None:
        """Keep one hook call: its tool-call row and gate span when it is a tool or shell event before it runs, and
        each finding with the word Claude Code was given; the end of a reply that may end closes the turn.

        Args:
            event: the hook call.
            plan: the plan in force in its session, or None.
            verdict: the verdict decide gave.
        """
        word = CLAUDE_DECISION.get(verdict.decision, verdict.decision)

        def change(con: Any, rec: Any) -> None:
            activity.record_call(con, rec, event, plan, word, verdict.findings)
            if event.kind == "Stop" and event.session and verdict.decision not in CLAUDE_DECISION:
                activity.turn_close(con, event.session)
        self.recorded(f"{event.kind} {event.tool or ''}".strip(), change)

    def span(self, session: Optional[Callable[[], str]], kind: str, status: str, name: str, attrs: dict[str, Any]) -> None:
        """Keep one span of a run of a harness action.

        Args:
            session: session() -> the calling session's id, or None when the server has no such port.
            kind: the span's kind (tool).
            status: ok or error.
            name: "<block>.<action>".
            attrs: its detail (the names of its arguments).
        """
        def change(con: Any, rec: Any) -> None:
            activity.span(con, session() if session else "", kind, status, name, attrs)
        self.recorded(name, change)
