"""The user's own prompts: each opens a turn and is kept in pl_prompts (masked, at most 64 KB), and a bare agreement
word typed while a plan waits approves nothing: only the form does (FORM_ONLY)."""
from __future__ import annotations

import re
import sqlite3
from typing import Optional

from harness.utils.contracts import YES
from harness.utils.ledger import activity
from harness.utils.plan.render import REFINE_LABEL

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
    """A prompt opens a turn (pl_turns) and is kept under the turn's number in pl_prompts: secrets masked, cut at 64 KB,
    marked when another session sent it (utils/ledger/activity.py). An empty prompt opens its turn and keeps no text.

    Args:
        con: the connection of the transaction.
        sid: the Claude Code session id.
        text: the prompt; None is kept as "".
    """
    text = str(text or "")
    n = activity.turn_open(con, sid, len(text))
    if text:
        activity.prompt(con, sid, n, text)
