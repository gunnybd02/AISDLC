"""Writes: what a session itself wrote and ran, recorded by the harness (docs/12-ledger.md), as rows of the caller's
transaction.
- rec_edits: each file a tool wrote, or a shell line whose targets can be read, with the hash of its content after
  the write (the id git gives the content; "" for a file that is gone). The row's service column holds
  "wrote:<hash>:<real path>"; the same path and content again counts up. The Stop guard reads it to tell a change
  another writer made (utils/plan/stop.py).
- pl_maint_runs: each shell line, a start row before it runs and an end row after (ok, failed, interrupted), secrets
  masked, cut at 4000 characters: a line that never reports still has its start row.
- pl_notes of kind shell.before: the snapshots of an unclear line checked after it ran (auto mode,
  utils/shell/after.py), kept under its call id before it runs."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from typing import Any, Optional

from harness.utils.contracts import Event, now
from harness.utils.ledger.mask import stored
from harness.utils.shapes import Facts
from harness.utils.shell.place_ops import shell_places

SHELLS = {"Bash": "bash", "PowerShell": "powershell"}
SHELL_MOST = 4000
MARK = "wrote:"
CODES = ("exit_code", "exitCode", "returncode", "code")
BEFORE = "shell.before"


def keep_before(con: sqlite3.Connection, sid: str, call: str, shots: dict[str, dict[str, str]]) -> None:
    """Keep the snapshots taken before an unclear line runs, under its call id.

    Args:
        con: the connection of the transaction.
        sid: the session id.
        call: the call id (tool_use_id) that pairs the line with its result.
        shots: {top folder of a repository: {path: content hash}}.
    """
    con.execute("INSERT INTO pl_notes (uid, kind, target, key, text, why, sid, at) VALUES (?, ?, ?, '', ?, '', ?, ?)",
                (uuid.uuid4().hex, BEFORE, call, json.dumps(shots, sort_keys=True), sid, now()))


def before_of(con: sqlite3.Connection, call: str) -> Optional[dict[str, dict[str, str]]]:
    """The snapshots kept before the line of a call ran.

    Args:
        con: an open connection to the ledger.
        call: the call id.

    Returns:
        {top folder: snapshot}; None when none was kept for it (a line that was not checked after) or it cannot be read.
    """
    if not call:
        return None
    row = con.execute("SELECT text FROM pl_notes WHERE kind = ? AND target = ? ORDER BY at DESC, rowid DESC LIMIT 1",
                      (BEFORE, call)).fetchone()
    try:
        shots = json.loads(row[0]) if row else None
    except ValueError:
        return None
    return shots if isinstance(shots, dict) else None


def real(path: str) -> str:
    """A path as the ledger names a file: its real path, links resolved, forward slashes.

    Args:
        path: a file path.

    Returns:
        The real path.
    """
    return os.path.realpath(path).replace("\\", "/")


def content_hash(path: str) -> str:
    """The id git gives the content of a file (as git hash-object does, no filter), or "" when there is no file.

    Args:
        path: the file.

    Returns:
        The hex sha1 of "blob <size>" and the bytes; "" for a missing or unreadable file.
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return ""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def wrote(con: sqlite3.Connection, sid: str, path: str) -> None:
    """Keep that the session wrote a file with the content it has now (or deleted it).

    Args:
        con: the connection of the transaction.
        sid: the session id.
        path: the file written or deleted.
    """
    at = now()
    con.execute("INSERT INTO rec_edits (sid, plan_id, service, first_at, last_at, edits, uid) VALUES (?, 0, ?, ?, ?, 1, ?) "
                "ON CONFLICT(sid, plan_id, service) DO UPDATE SET last_at = excluded.last_at, edits = edits + 1",
                (sid, f"{MARK}{content_hash(real(path))}:{real(path)}", at, at, uuid.uuid4().hex))


def written(con: sqlite3.Connection, sid: str) -> dict[str, set[str]]:
    """Every content the session wrote, by file.

    Args:
        con: an open connection to the ledger.
        sid: the session id.

    Returns:
        {real path: the hashes of every content the session gave it ("" for a delete)}.
    """
    out: dict[str, set[str]] = {}
    for (text,) in con.execute("SELECT service FROM rec_edits WHERE sid = ? AND service LIKE ?", (sid, MARK + "%")):
        digest, _, path = text[len(MARK):].partition(":")
        out.setdefault(path, set()).add(digest)
    return out


def outcome(response: Any) -> tuple[str, int]:
    """How a shell line ended, from the tool's answer.

    Args:
        response: the answer of the shell tool as the hook gives it.

    Returns:
        ("interrupted", -1), ("failed", its exit code, -1 when unknown) or ("ok", its exit code, -1 when unknown).
    """
    if not isinstance(response, dict):
        return "ok", -1
    if response.get("interrupted"):
        return "interrupted", -1
    code = next((response[k] for k in CODES if isinstance(response.get(k), int) and not isinstance(response[k], bool)), None)
    if code is not None:
        return ("ok" if code == 0 else "failed"), code
    return ("failed" if response.get("is_error") else "ok"), -1


def shell_row(con: sqlite3.Connection, sid: str, command: str, cwd: str, state: str, code: int) -> None:
    """Keep one row of a shell line: its start, or how it ended.

    Args:
        con: the connection of the transaction.
        sid: the session id.
        command: the shell line.
        cwd: the folder it runs in.
        state: start, ok, failed or interrupted.
        code: its exit code; -1 for a start, an interrupted run or an unknown code.
    """
    con.execute("INSERT INTO pl_maint_runs (uid, door, fault, approver, command, cwd, exit, output, sid, at) VALUES "
                "(?, 'shell', '', '', ?, ?, ?, ?, ?, ?)", (uuid.uuid4().hex, stored(command, SHELL_MOST)[0],
                                                          stored(cwd, SHELL_MOST)[0], code, state, sid, now()))


def record(con: sqlite3.Connection, event: Event, facts: Facts) -> None:
    """Keep what a hook call wrote and ran: a shell line's start row before it runs, and the snapshots of a line checked
    after it runs; after a call ran, a shell line's end row and each file the call wrote, with its content.

    Args:
        con: the connection of the transaction.
        event: the hook call.
        facts: the facts of the call (writes: the files an editing tool writes; after_before: the snapshots of an
            unclear line in auto mode).
    """
    sid, given = event.session or "", event.input if isinstance(event.input, dict) else {}
    dialect, command = SHELLS.get(event.tool), given.get("command")
    targets = []
    if dialect and isinstance(command, str):
        if event.kind == "PreToolUse":
            shell_row(con, sid, command, event.cwd, "start", -1)
            if facts.get("after_before") is not None and event.call:
                keep_before(con, sid, event.call, facts["after_before"])
        elif event.kind == "PostToolUse":
            shell_row(con, sid, command, event.cwd, *outcome(event.response))
            seen = shell_places(command, dialect, event.cwd, "").get("writes", []) + list(facts.get("after_writes") or [])
            targets = list(dict.fromkeys(real(path) for path in seen))  # a file both read and found after counts once
    elif event.kind == "PostToolUse":
        targets = facts.get("writes", [])
    for path in targets:
        wrote(con, sid, path)
