"""The maint grant: only the user's approval word to the form question 'Turn guards off for N min: <why>?' turns every guard
off, for N minutes, at most 120. It is a row of the ledger (pl_notes, kind maint.grant, text {"until": seconds}), and
every call that passes while it lasts is a row of pl_logs.

harness/entry/hook.py writes and reads these rows itself, with plain sqlite3, so the grant works when the harness is broken:
the one place outside utils/ledger/db.py that opens the ledger. KIND, MAX_MINUTES and the question must match it
(harness/tests/utils/test_grant.py checks they do)."""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Optional

from harness.utils.contracts import YES
from harness.utils.shapes import Row

KIND = "maint.grant"
MAX_MINUTES = 120
QUESTION = re.compile("^Turn guards off for (\\d+) min: (.+)\\?$")
LATEST = "SELECT text, why, at FROM pl_notes WHERE kind = ? ORDER BY at DESC, rowid DESC LIMIT 1"


def question(minutes: int, why: str) -> str:
    """The form question that asks the user for a grant of minutes, and what to tell the model.

    Args:
        minutes: how long the guards are to be off, a whole number from 1 to MAX_MINUTES.
        why: the reason, put in the question (spaces folded, a trailing "?" taken off).

    Returns:
        The text for the model: ask the user the exact question, with its two options.

    Raises:
        ValueError: minutes is out of range or not an int, the reason is empty, or it cannot be put in the question.
    """
    if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= MAX_MINUTES:
        raise ValueError(f"minutes is a whole number from 1 to {MAX_MINUTES}")
    why = " ".join(str(why).split()).rstrip("?")
    if not why:
        raise ValueError("say why the guards should be off")
    q = f"Turn guards off for {minutes} min: {why}?"
    if not QUESTION.match(q):
        raise ValueError("the reason cannot be put in the question")
    return (f"Ask the user now with AskUserQuestion, one question, exactly: {q} Options: \"{YES}\", "
            f"\"Deny\". Never fill in the answer. Only the user's {YES} turns the guards off; every call is "
            f"traced while they are off.")


def active(rows: Callable[[str, tuple[Any, ...]], list[Row]], now: Optional[float] = None) -> Optional[dict[str, Any]]:
    """{until, why} of the grant that lasts now, or None; rows reads the ledger (sql, args). A grant that reaches
    further than MAX_MINUTES from now is no grant: only the hook writes one, and never so long.

    Args:
        rows: rows(sql, args) -> the rows of a query on the ledger (PlanStore.rows).
        now: the time in seconds since the epoch; None for the clock.

    Returns:
        {"until": seconds (float), "why": the reason} of the newest grant while it lasts; None otherwise.
    """
    now = time.time() if now is None else now
    for row in rows(LATEST, (KIND,)):
        try:
            until = float(json.loads(row["text"])["until"])
        except (ValueError, KeyError, TypeError):
            return None
        return {"until": until, "why": row["why"]} if now < until <= now + MAX_MINUTES * 60 else None
    return None
