"""The user's own prompts: each is kept in pl_prompts (at most 2000 characters), and a bare agreement word typed while
a plan waits approves nothing: only the form does (FORM_ONLY)."""
import re
import time

LONGEST = 2000
AGREE = {"ok", "okay", "oke", "yes", "y", "go", "go ahead", "approve", "approved", "lgtm", "ship it",
         "duyệt", "đồng ý", "làm đi", "chốt", "ừ", "được", "đi"}
FORM_ONLY = ("GATE: a word in the chat approves no plan. Plan {plan} rev {rev} waits: ask the user its form question "
             "with AskUserQuestion; only the answer in the form approves it.")


def bare_agreement(text):
    words = " ".join(re.sub(r"[^\w\s]", " ", str(text).lower()).split())
    return words in AGREE


def record_prompt(con, sid, text):
    text = str(text or "")
    n = 1 + (con.execute("SELECT MAX(n) FROM pl_prompts WHERE sid = ?", (sid,)).fetchone()[0] or 0)
    con.execute("INSERT INTO pl_prompts (sid, n, text, chars, cut, from_peer, source, uuid, at) VALUES "
                "(?, ?, ?, ?, ?, 0, 'user', '', ?)", (sid, n, text[:LONGEST], len(text), int(len(text) > LONGEST),
                                                     int(time.time() * 1000)))
