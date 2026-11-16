"""The user's own prompts: each is kept in pl_prompts (at most 2000 characters), and a bare agreement word typed while
a plan waits approves nothing: only the form does (FORM_ONLY)."""
from __future__ import annotations

import re
import sqlite3
import time
from typing import Optional

from harness.utils.contracts import YES
from harness.utils.plan.render import REFINE_LABEL

LONGEST = 2000
# Words a user may type to agree, in English and Vietnamese: recognised in a prompt, never shown.
AGREE = {"ok", "okay", "oke", "yes", "y", "go", "go ahead", "approve", "approved", "lgtm", "ship it",
         "duy\u1ec7t", "\u0111\u1ed3ng \u00fd", "l\u00e0m \u0111i", "ch\u1ed1t", "\u1eeb", "\u0111\u01b0\u1ee3c", "\u0111i"}
FORM_ONLY = ("GATE: a word typed in the chat approves no plan. Plan {plan} rev {rev} waits for its approval form: ask "
             "the user with AskUserQuestion, one question, exactly: {question} Options: \"" + YES + "\", \""
             + REFINE_LABEL + "\". Never fill in the answer; only the user's \"" + YES + "\" in the form approves it.")


def bare_agreement(text: str) -> bool:
    """Whether a prompt is only an agreement word (ok, yes, lgtm...), punctuation and case ignored.

    Args:
        text: the user's prompt.

    Returns:
        True when the prompt's words are one entry of AGREE.
    """
    words = " ".join(re.sub(r"[^\w\s]", " ", str(text).lower()).split())
    return words in AGREE


def record_prompt(con: sqlite3.Connection, sid: str, text: Optional[str]) -> None:
    """Keep one prompt of the user in pl_prompts, cut to LONGEST characters, numbered from 1 in its session.

    Args:
        con: the connection of the transaction.
        sid: the Claude Code session id.
        text: the prompt; None is kept as "".
    """
    text = str(text or "")
    n = 1 + (con.execute("SELECT MAX(n) FROM pl_prompts WHERE sid = ?", (sid,)).fetchone()[0] or 0)
    con.execute("INSERT INTO pl_prompts (sid, n, text, chars, cut, from_peer, source, uuid, at) VALUES "
                "(?, ?, ?, ?, ?, 0, 'user', '', ?)", (sid, n, text[:LONGEST], len(text), int(len(text) > LONGEST),
                                                     int(time.time() * 1000)))
