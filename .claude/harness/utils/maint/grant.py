"""The maint grant: only the user's approval word to the form question 'T\u1eaft guard N ph\u00fat: <why>?' turns every guard
off, for N minutes, at most 120. It is a row of the ledger (pl_notes, kind maint.grant, text {"until": seconds}), and
every call that passes while it lasts is a row of pl_logs.

entry/hook.py writes and reads these rows itself, with plain sqlite3, so the grant works when the harness is broken:
the one place outside utils/ledger/db.py that opens the ledger. KIND, MAX_MINUTES and the question must match it
(tests/utils/test_grant.py checks they do)."""
import json
import re
import time

from harness.utils.contracts import YES

KIND = "maint.grant"
MAX_MINUTES = 120
QUESTION = re.compile("^T\u1eaft guard (\\d+) ph\u00fat: (.+)\\?$")
LATEST = "SELECT text, why, at FROM pl_notes WHERE kind = ? ORDER BY at DESC, rowid DESC LIMIT 1"


def question(minutes, why):
    """The form question that asks the user for a grant of minutes, and what to tell the model."""
    if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= MAX_MINUTES:
        raise ValueError(f"minutes is a whole number from 1 to {MAX_MINUTES}")
    why = " ".join(str(why).split()).rstrip("?")
    if not why:
        raise ValueError("say why the guards should be off")
    q = f"T\u1eaft guard {minutes} ph\u00fat: {why}?"
    if not QUESTION.match(q):
        raise ValueError("the reason cannot be put in the question")
    return (f"Ask the user now with AskUserQuestion, one question, exactly: {q} Options: \"{YES}\", "
            f"\"Kh\u00f4ng\". Never fill in the answer. Only the user's {YES} turns the guards off; every call is "
            f"traced while they are off.")


def active(rows, now=None):
    """{until, why} of the grant that lasts now, or None; rows reads the ledger (sql, args). A grant that reaches
    further than MAX_MINUTES from now is no grant: only the hook writes one, and never so long."""
    now = time.time() if now is None else now
    for row in rows(LATEST, (KIND,)):
        try:
            until = float(json.loads(row["text"])["until"])
        except (ValueError, KeyError, TypeError):
            return None
        return {"until": until, "why": row["why"]} if now < until <= now + MAX_MINUTES * 60 else None
    return None
