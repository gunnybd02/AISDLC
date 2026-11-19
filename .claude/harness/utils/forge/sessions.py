"""Sessions: the model a cloud session opens on (docs/system.md section 12). Sonnet (DEFAULT_MODEL) is the default; a
create_session call (TOOL, whatever its server is named) on another model runs only with a one-use pass for exactly
that call: before it, the harness refuses it and gives the form question (gear/translate/session.py, the when row
session.no_pass); the user's Allow to that question writes the pass in pl_asks (accepts); a call that opened a session
uses it (used), so the next costly session asks again; merges.held, the one reader of a one-use pass, reads it. A
call that names no model would copy the parent's model: it is refused (session.no_model) and told to name one."""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from harness.utils.shapes import PlanStore

TOOL = "__create_session"  # the cloud tool that opens a session, whatever its server is named
DEFAULT_MODEL = "claude-sonnet-5-5"  # the model every session opens on unless the user allows another
ALLOW_LABEL, NO_LABEL = "Allow", "Deny"  # the labels of the session form
ASKED = re.compile(r'^Open a session on \S+: ".*" \[(?P<code>s[0-9a-f]{12})\]\?')
OPENED = re.compile(r"session_[0-9A-Za-z]{8,}")


def is_call(tool: Any) -> bool:
    """Whether a tool name is the cloud tool that opens a session (mcp__<server>__create_session)."""
    name = str(tool or "")
    return name.startswith("mcp__") and name.endswith(TOOL)


def model_of(given: Any) -> str:
    """The model a create_session call names, in lower case; "" when it names none."""
    return str((given if isinstance(given, dict) else {}).get("model") or "").strip().lower()


def free(model: str) -> bool:
    """Whether a session on this model needs no form: only the default model."""
    return model == DEFAULT_MODEL


def title_of(given: Any) -> str:
    """The call's title on one line, 80 characters at most, double quotes made single ("" when it has none)."""
    title = str((given if isinstance(given, dict) else {}).get("title") or "")
    return " ".join(title.split())[:80].replace('"', "'")


def code_of(model: str, title: str, prompt: str) -> str:
    """The code of one session call: its model, title and prompt.

    Returns:
        "s" and 12 hex characters of the sha256 of the three (the prompt by its own sha256).
    """
    text = json.dumps([model.lower(), title, hashlib.sha256(prompt.encode("utf-8")).hexdigest()])
    return "s" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def call_code(given: Any) -> str:
    """The code of a create_session call's input: code_of its model, one-line title and prompt."""
    prompt = str((given if isinstance(given, dict) else {}).get("prompt") or "")
    return code_of(model_of(given), title_of(given), prompt)


def question(given: Any) -> str:
    """The form question the user answers for one create_session call.

    Returns:
        'Open a session on <model>: "<title>" [<code>]?'.
    """
    return f'Open a session on {model_of(given)}: "{title_of(given)}" [{call_code(given)}]?'


def accepts(port: PlanStore, answers: dict[str, str]) -> list[str]:
    """Keep the user's Allow to a session question as a one-use pass of exactly that call (its code).

    Args:
        port: the ledger port.
        answers: {form question: the label the user chose} of an AskUserQuestion call.

    Returns:
        One GATE note per session question answered Allow; [] when none was.
    """
    notes = []
    for asked, label in (answers or {}).items():
        found = ASKED.match(str(asked))
        if found and str(label).strip() == ALLOW_LABEL:
            port.write(lambda con, rec, code=found["code"]: con.execute(
                "INSERT OR REPLACE INTO pl_asks (sid, key, at, used) VALUES ('', ?, ?, 0)", (code, int(time.time() * 1000))))
            notes.append(f"GATE: the user allows the session [{found['code']}]: call create_session again, once, with "
                         "the same model, title and prompt.")
    return notes


def used(port: PlanStore, event: Any) -> list[str]:
    """After a create_session call that opened a session (its answer holds a session id): its pass is used.

    Args:
        port: the ledger port.
        event: the PostToolUse hook call of any tool.

    Returns:
        [] always: the use is recorded, nothing is told.
    """
    if event.kind != "PostToolUse" or not is_call(event.tool):
        return []
    text = event.response if isinstance(event.response, str) else json.dumps(event.response)
    if not OPENED.search(text or ""):
        return []
    code = call_code(event.input)
    port.write(lambda con, rec: con.execute("UPDATE pl_asks SET used = 1 WHERE sid = '' AND key = ?", (code,)))
    return []
