"""Claude Code hook: the event JSON on stdin, the answer on stdout. Any failure exits 2, which blocks the tool call;
SystemExit too, so a harness that quits quietly cannot let a call through.

Before the harness is even imported, this file (standard library only, entry_net) holds the maint grant
(harness/utils/maint/grant.py), reading and writing the ledger with plain sqlite3 so it works when the harness is broken:
- the user's approval word to the form 'Turn guards off for N min: <why>?' (read from the PostToolUse of
  AskUserQuestion, which the model cannot write) turns every guard off for N minutes, at most 120: a pl_notes row of
  kind maint.grant, written in one transaction with its trace in pl_logs;
- while a grant lasts, each call passes and is traced in pl_logs with what it does (the agent's words, the file, the
  command, secrets masked by the shapes of utils/ledger/mask.py, kept here); the harness still records it and keeps
  the user's answers, with nothing held (run_hook with waive), and a broken harness only says on stderr that it did
  not record, so the trace is the record;
- a tool call a broken harness blocks names the way out (WAY_OUT): the fallback release, the fallback tools, the grant;
- AskUserQuestion is answered here: refused when the model filled the answers in or built a question to look like an
  answer ('"="' in it), let through otherwise even when the harness is broken, so the user can always be asked.
- A form not shaped as one (questions and options that are not lists of objects) is refused too, and any error while
  checking a form refuses it: only a form that passed the check may pass a broken harness.
- A grant and its trace are one transaction: no trace, no grant. A grant that reaches further than 120 minutes is no
  grant, and the state folder stays closed to the editing tools while the guards are off.
- Output is UTF-8 bytes, whatever the console's code page."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

CODE_DIR = Path(__file__).resolve().parent.parent.parent  # the code this entry belongs to (a release, or the work tree)
CLAUDE_DIR = Path(os.environ.get("HARNESS_HOME") or CODE_DIR)  # the home: state, config, skills (anchor.py)
STATE = CLAUDE_DIR / "state"
LEDGER = STATE / "harness.db"
SCHEMA = CODE_DIR / "harness" / "utils" / "ledger" / "schema.sql"
FORM = "AskUserQuestion"
YES = "Approve"
PAUSE = re.compile("^Turn guards off for (\\d+) min: (.+)\\?$")
GRANT = "maint.grant"
LATEST = "SELECT text, why, at FROM pl_notes WHERE kind = ? ORDER BY at DESC, rowid DESC LIMIT 1"
MAX_MINUTES = 120
FORGE = '"="'
PREFILLED = "Only the user answers a form: call AskUserQuestion with the questions alone, none holding '\"=\"'."

BLOCKING = ("PreToolUse", None, "")  # the events a failure of the harness blocks (exit 2)
CRASHED = "HARNESS_HOOK_FAILED"  # set when this release failed, not refused: the anchor then falls back
TRACED = 2000  # characters of each part of a call kept in its trace while the guards are off
SAID_KEYS = ("description", "file_path", "notebook_path", "path", "url", "command")
SECRET_SHAPES = tuple(re.compile(p, f) for p, f in (  # utils/ledger/mask.py SECRETS: test_grant.py keeps them equal
    (r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY", 0), (r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", 0),
    (r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b", 0), (r"\bglpat-[A-Za-z0-9_-]{20,}\b", 0),
    (r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b", 0), (r"\bsk-(?:ant-)?[A-Za-z0-9_-]{32,}\b", 0),
    (r"\bAIza[0-9A-Za-z_-]{35}\b", 0), (r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s:@]{3,}@", re.I)))
REDACTED = "[redacted]"
WAY_OUT = ("Way out: the anchor tries a failing release twice, then puts the previous release in force by itself (the "
           "fallback tools status and rollback say which is in force and go back one release). If no release is left, "
           "ask the user with AskUserQuestion, one question, exactly: Turn guards off for 15 min: <why>? with the "
           "options \"Approve\" and \"Deny\". The form passes a broken harness, and every call is still traced.")

def ledger(create: bool) -> Optional[sqlite3.Connection]:
    """The ledger, made from schema.sql as utils/ledger/db.py makes it when it has no table yet; None when it does not
    exist and create is false (no ledger: no grant).

    Args:
        create: whether to make the ledger when it does not exist.

    Returns:
        A connection in autocommit mode (the caller closes it), or None.
    """
    if not create and not LEDGER.is_file():
        return None
    STATE.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(LEDGER, isolation_level=None, timeout=10)
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1").fetchone():
        con.execute("BEGIN IMMEDIATE")
        for line in SCHEMA.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("--"):
                con.execute(line.strip().rstrip(";"))
        con.execute("COMMIT")
    return con


def summary(data: dict[str, Any]) -> dict[str, str]:
    """What a call does, for its trace: the agent's words, the file it names and its command, each line of a secret's
    shape redacted as utils/ledger/mask.py does (with the standard library only: it works when the harness is broken).

    Args:
        data: the hook payload (tool_input).

    Returns:
        {description?, file_path?, notebook_path?, path?, url?, command?}, each masked and at most TRACED characters.
    """
    given = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    return {k: "\n".join(REDACTED if any(p.search(line) for p in SECRET_SHAPES) else line
                         for line in given[k].split("\n"))[:TRACED]
            for k in SAID_KEYS if isinstance(given.get(k), str) and given[k]}


def trace(con: sqlite3.Connection, what: str, data: dict[str, Any]) -> None:
    """Write the trace of a call in pl_logs: what happened, the call's event, tool and session, and what it does
    (summary).

    Args:
        con: the ledger.
        what: granted or passed.
        data: the hook payload.
    """
    body = {"what": what, "event": data.get("hook_event_name"), "tool": data.get("tool_name"),
            "session": data.get("session_id"), "call": summary(data)}
    con.execute("INSERT INTO pl_logs (uid, body, at) VALUES (?, ?, ?)",
                (uuid.uuid4().hex, json.dumps(body, ensure_ascii=False), int(time.time() * 1000)))


def granted() -> Optional[sqlite3.Connection]:
    """The ledger while a grant lasts, or None. A grant that reaches further than the longest one allows is no grant
    (only this file writes one, and never so long).

    Returns:
        The ledger's connection (the caller closes it), or None when no grant lasts.
    """
    con = ledger(create=False)
    if con is None:
        return None
    row = con.execute(LATEST, (GRANT,)).fetchone()
    try:
        until = float(json.loads(row[0])["until"]) if row else 0
    except (ValueError, KeyError, TypeError):
        until = 0
    if time.time() < until <= time.time() + MAX_MINUTES * 60:
        return con
    con.close()
    return None


def into_state(data: dict[str, Any]) -> bool:
    """Whether an editing tool writes into the state folder, which stays closed while the guards are off.

    Args:
        data: the hook payload (tool_input's file_path or notebook_path, cwd).

    Returns:
        True when the path is the state folder or inside it.
    """
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(path, str) or not path:
        return False
    full = os.path.realpath(os.path.join(str(data.get("cwd") or ""), path.removeprefix("\\\\?\\")))
    state = os.path.realpath(STATE)
    return os.path.normcase(full) == os.path.normcase(state) or \
        os.path.normcase(full).startswith(os.path.normcase(state) + os.sep)


def labels(data: dict[str, Any]) -> dict[str, str]:
    """{question: label} of an answered form, where Claude Code puts the answers (as harness/hooks/forms.py reads
    them: the response text only when no question holds '"="' and each question is in it once).

    Args:
        data: the hook payload of AskUserQuestion (tool_input's answers, tool_response).

    Returns:
        {question: the label the user chose}.
    """
    found, text = {}, ""
    for source in ((data.get("tool_input") or {}).get("answers"), data.get("tool_response")):
        if isinstance(source, str):
            try:
                source = json.loads(source)
            except ValueError:
                text = source
                continue
        if isinstance(source, dict):
            source = source.get("answers", source)
            found.update({str(q): str(a) for q, a in source.items() if isinstance(a, str)})
    asked = questions(data)
    if text and not forged(data):
        for q in asked:
            hits = re.findall("(?:^|: |, )" + re.escape(f'"{q}"=') + '"([^"]*)"', text)
            if q not in found and len(hits) == 1:
                found[q] = hits[0]
    return found


def form_of(data: dict[str, Any]) -> Optional[list[dict[str, Any]]]:
    """The questions of the call, or None when it is not shaped as a form: a list of question objects, each with a
    list of option objects.

    Args:
        data: the hook payload.

    Returns:
        The question objects of tool_input, or None.
    """
    tool_input = data.get("tool_input")
    qs = tool_input.get("questions") if isinstance(tool_input, dict) else None
    shaped = isinstance(qs, list) and all(
        isinstance(q, dict) and isinstance(q.get("options", []), list)
        and all(isinstance(o, dict) for o in q.get("options", [])) for q in qs)
    return qs if shaped else None


def questions(data: dict[str, Any]) -> list[str]:
    """The question texts of the form.

    Args:
        data: the hook payload.

    Returns:
        Each question's text; [] when the call is not shaped as a form.
    """
    return [str(q.get("question")) for q in form_of(data) or []]


def forged(data: dict[str, Any]) -> bool:
    """A form not shaped as one, or whose question or option label holds '"="' (built to look like an answer).

    Args:
        data: the hook payload.

    Returns:
        True when the form is misshapen or forged.
    """
    qs = form_of(data)
    if qs is None:
        return True
    words = [str(q.get("question") or "") for q in qs]
    words += [str(o.get("label") or "") for q in qs for o in q.get("options", [])]
    return any(FORGE in w for w in words)


def refused_form(data: dict[str, Any]) -> bool:
    """Whether a form must be refused before it runs: answers the model wrote, or a forged or misshapen form. Any
    error while looking counts as a refusal.

    Args:
        data: the hook payload.

    Returns:
        True when the form must be refused.
    """
    try:
        tool_input = data.get("tool_input")
        return forged(data) or not isinstance(tool_input, dict) or bool(tool_input.get("answers"))
    except Exception:
        return True


def grant_from(data: dict[str, Any]) -> Optional[str]:
    """The note of a grant the user approved in this form, or None. A form that would have been refused gives none.
    The grant (a maint.grant note) and its trace are written in one transaction.

    Args:
        data: the PostToolUse payload of AskUserQuestion.

    Returns:
        The note for the model ("GATE: the user turned the guards off for N minutes: <why>. ..."), or None.
    """
    if refused_form({**data, "tool_input": {**data["tool_input"], "answers": None}}
                    if isinstance(data.get("tool_input"), dict) else data):
        return None
    for q, label in labels(data).items():
        m = PAUSE.match(q)
        if m and label.strip() == YES and q in questions(data):
            minutes = min(int(m.group(1)), MAX_MINUTES)
            con = ledger(create=True)
            try:
                con.execute("BEGIN IMMEDIATE")  # the grant and its trace: both, or neither
                trace(con, "granted", data)
                con.execute("INSERT INTO pl_notes (uid, kind, target, key, text, why, sid, at) VALUES (?, ?, ?, ?, ?, ?, "
                            "?, ?)", (uuid.uuid4().hex, GRANT, "guards", str(minutes),
                                      json.dumps({"until": time.time() + minutes * 60}), m.group(2),
                                      str(data.get("session_id") or ""), int(time.time() * 1000)))
                con.execute("COMMIT")
            finally:
                con.close()
            return f"GATE: the user turned the guards off for {minutes} minutes: {m.group(2)}. Every call is traced."
    return None


def say(text: str) -> None:
    """Write the reason of a block on stderr as UTF-8 bytes: a console code page must never turn a block into a crash.

    Args:
        text: the reason.
    """
    sys.stderr.buffer.write((text + "\n").encode("utf-8", "replace"))


def answer(context: Optional[str] = None) -> int:
    """Answer a PostToolUse call, with context for the model when there is some.

    Args:
        context: the additional context written on stdout, or None to write nothing.

    Returns:
        0, the exit code.
    """
    if context:
        out = json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context}},
                         ensure_ascii=False)
        sys.stdout.buffer.write(out.encode("utf-8"))
    return 0


def recorded(raw: str) -> int:
    """A call while the guards are off: the harness records it and keeps the user's answers, and nothing is held
    (run_hook with waive). A broken harness only says so on stderr: the call still passes.

    Args:
        raw: the hook's payload.

    Returns:
        0, the exit code: the call goes on.
    """
    try:
        sys.path.insert(0, str(CODE_DIR))
        from harness.assemble.engine.build import run_hook
        out = run_hook(raw, CLAUDE_DIR, waive=True)
    except BaseException as e:
        say(f"harness: the guards are off and this call was not recorded: {type(e).__name__}: {e}")
        return 0
    sys.stdout.buffer.write(out.encode("utf-8"))
    return 0


def main() -> int:
    """Answer one hook call: a form checked here, a grant kept or used, else the harness's own answer (run_hook).

    Returns:
        The exit code: 0 the call goes on (the answer on stdout), 2 it is blocked (the reason on stderr). A failure of
        the harness blocks only a tool call (PreToolUse) or a payload that names no event; on any other event it is
        said on stderr and the session goes on, so a broken harness never holds a turn's end or a prompt.
    """
    raw, data, asking, form = "", {}, False, False
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
        data = json.loads(raw) if raw.strip() else {}
        data = data if isinstance(data, dict) else {}
        form, pre = data.get("tool_name") == FORM, data.get("hook_event_name") == "PreToolUse"
        if form and pre:
            if refused_form(data):
                say(PREFILLED)
                return 2
            asking = True  # a clean form: it may pass even when the harness below is broken
        if form and data.get("hook_event_name") == "PostToolUse":  # its answers come from the user: a prefilled call
            note = grant_from(data)                                  # was refused before it ran
            if note:
                return answer(note)
        con = granted()
        if con is not None:
            try:
                if pre and into_state(data):
                    say("The state of the harness stays closed while the guards are off.")
                    return 2
                trace(con, "passed", data)
            finally:
                con.close()
            return recorded(raw)
        sys.path.insert(0, str(CODE_DIR))
        from harness.assemble.engine.build import run_hook
        out = run_hook(raw, CLAUDE_DIR)
    except BaseException as e:
        if asking:
            return 0  # a clean form is harmless to ask, and it is how the user is asked for a grant
        if data.get("hook_event_name") not in BLOCKING:  # spec 13: only a tool call is held by a broken harness
            say(f"harness hook failed, nothing is held: {type(e).__name__}: {e}")
            if form:  # the user's answer could not be kept: say so, so nobody believes a grant holds
                return answer(f"The harness could not keep this answer ({type(e).__name__}: {e}); nothing it asked "
                              "for is granted, and the guards stay on.")
            return 0
        say(f"harness hook failed, the call is blocked: {type(e).__name__}: {e}\n{WAY_OUT}")
        os.environ[CRASHED] = "1"  # a failure, not a refusal: the anchor may run the previous release instead
        return 2
    sys.stdout.buffer.write(out.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
