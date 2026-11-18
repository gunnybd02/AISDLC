"""Store: what a ledger knows of its copies outside the machine (a Google Drive folder; export.py makes a copy). It is
kept as rows of pl_notes, so the schema stays the pinned one and every copy carries its own story:

  store.ledger    key = the ledger's id, given once: a ledger that starts again on a new machine is another ledger
  store.export    key = the copy's number, target = its file name, text = who and when (ledger, seq, session, reason,
                  at, commit, repo, branch, harness, mark); written before the copy is made, so the copy holds it
  store.uploaded  key = the copy's number, target = its file name, text = the Drive file's id; written when the
                  hook sees an MCP tool's create_file answer with that file
  store.asked     key = the mark a turn was held for, so a turn is held once for the same work
  store.folder    target = db or tickets, key = the store folder's id, text = the subfolder's Drive id; written when
                  the hook sees a Drive answer show that folder under the store folder (made, or listed by a search)
  store.ticket    target = a ticket file's name, key = its sha256 (utils/orchestra/issues.py); store.ticket_uploaded
                  its Drive id, when the hook sees create_file answer with it

The mark counts what must not be lost: commits, plan events (approved, delivered, dropped), pushes and merge requests.
Work is unsaved while the mark is ahead of the mark of the newest copy the store holds. Small rows (verify receipts,
logs) wait for the next copy. The folder's id is the environment variable HARNESS_DRIVE_FOLDER: never in the tree."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from typing import TYPE_CHECKING, Optional

from harness.utils.ledger.db import pinned
from harness.utils.shapes import PlanStore, SavedCopy, StoreRecord

if TYPE_CHECKING:
    from harness.utils.contracts import Event
    from harness.utils.ledger.recorder import Recorder

ENV = "HARNESS_DRIVE_FOLDER"
REASONS = ("manual", "push", "plan-close", "turn-end", "handback")
TAG = re.compile(r"^orch\.pd-[a-z0-9-]{1,40}\.[a-z0-9][a-z0-9-]{0,39}$")  # the plan marker of an orchestra copy
LEDGER, EXPORT, UPLOADED, ASKED = "store.ledger", "store.export", "store.uploaded", "store.asked"
COUNTED = (("commit", "SELECT COUNT(*) AS n FROM rec_commits"),
           ("plan event", "SELECT COUNT(*) AS n FROM pl_plan_events WHERE event IN ('approved', 'delivered', 'dropped')"),
           ("push or merge request", "SELECT COUNT(*) AS n FROM pl_git_audit"))
NEWEST = "SELECT key, target, text, at FROM pl_notes WHERE kind = ? ORDER BY at DESC, rowid DESC LIMIT 1"
FILE_ID = re.compile(r'\\*"id\\*"\s*:\s*\\*"([A-Za-z0-9_-]{10,})')
FOLDER, PLACES = "store.folder", ("db", "tickets")  # the store's subfolders: ledger copies, ticket files
FOLDER_MIME = "application/vnd.google-apps.folder"
TICKET, TICKET_UP = "store.ticket", "store.ticket_uploaded"  # a ticket file made (key: its sha256), and uploaded


def folder() -> str:
    """The store's Drive folder id, from the environment.

    Returns:
        HARNESS_DRIVE_FOLDER without spaces around it, "" when it is not set.
    """
    return os.environ.get(ENV, "").strip()


def session_part(sid: Optional[str]) -> str:
    """The session id as a part of a copy's file name.

    Args:
        sid: the Claude Code session id, or None.

    Returns:
        The id with every character but letters, digits and "-" made "-", trimmed; "nosession" when nothing is left.
    """
    return re.sub(r"[^A-Za-z0-9-]", "-", str(sid or "")).strip("-") or "nosession"


def note(con: sqlite3.Connection, kind: str, target: str, key: str | int, text: str, sid: Optional[str],
         at: int) -> None:
    """Insert one row of pl_notes (a store row) with a new uid and no why.

    Args:
        con: the connection of the transaction.
        kind: the row's kind (LEDGER, EXPORT, UPLOADED or ASKED).
        target: what the row is about (a file name, "ledger", "turn").
        key: the row's key (the ledger's id, a copy's number, a mark as JSON); kept as text.
        text: the row's text (a record as JSON, a Drive file id, "").
        sid: the Claude Code session id, or None.
        at: the time in ms.
    """
    con.execute("INSERT INTO pl_notes (uid, kind, target, key, text, why, sid, at) VALUES (?, ?, ?, ?, ?, '', ?, ?)",
                (uuid.uuid4().hex, kind, target, str(key), text, str(sid or ""), at))


def mark_of(con: sqlite3.Connection) -> list[int]:
    """The mark of the ledger, read on a connection.

    Args:
        con: an open connection to the ledger.

    Returns:
        [commits, plan events, pushes and merge requests], in the order of COUNTED.
    """
    return [con.execute(sql).fetchone()[0] for _, sql in COUNTED]


def mark(port: PlanStore) -> list[int]:
    """The mark of the ledger, read through the port.

    Args:
        port: the harness ledger (plans, tickets, audit rows).

    Returns:
        [commits, plan events, pushes and merge requests], in the order of COUNTED; zeros with no ledger yet.
    """
    return [(port.rows(sql) or [{"n": 0}])[0]["n"] for _, sql in COUNTED]


def begin(port: PlanStore, sid: str, reason: str, where: Optional[dict[str, str]] = None,
          now: Optional[float] = None, tag: str = "") -> StoreRecord:
    """Keep the record of a new copy (and the ledger's id, the first time) and answer it: {ledger, seq, title, ...}.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        sid: the Claude Code session id that asks for the copy.
        reason: why the copy is made, one of REASONS.
        where: {repo, branch} the copy is asked from, added to the record; None or {} outside a repository.
        now: the time in seconds since the epoch; None for the clock.
        tag: the plan marker of a session of an orchestra run, "orch.<plan id>.<child name or parent>"
            (utils/orchestra/crew.store_tag); it goes in the title before the commit, so one Drive search lists
            every copy of a run; "" for none (a tag of another shape is left out).

    Returns:
        The record kept in pl_notes (StoreRecord): its title is the copy's file name.
    """
    seconds = time.time() if now is None else now
    at, stamp = int(seconds * 1000), time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(seconds))

    def change(con: sqlite3.Connection, rec: Recorder) -> StoreRecord:
        row = con.execute("SELECT key FROM pl_notes WHERE kind = ? ORDER BY at, rowid LIMIT 1", (LEDGER,)).fetchone()
        ledger = row[0] if row else uuid.uuid4().hex[:12]
        if not row:
            note(con, LEDGER, "ledger", ledger, "", sid, at)
        seq = 1 + con.execute("SELECT COUNT(*) FROM pl_notes WHERE kind = ?", (EXPORT,)).fetchone()[0]
        last = con.execute("SELECT commit_sha FROM rec_commits ORDER BY at DESC, rowid DESC LIMIT 1").fetchone()
        commit = str(last[0])[:7] if last and last[0] else "nocommit"
        schema = f"s{pinned()[:8]}"
        plan = tag if TAG.match(tag or "") else ""
        title = (f"{session_part(sid)}__{ledger[:6]}-{seq:03d}__{stamp}__{reason}__{plan + '__' if plan else ''}"
                 f"{commit}__{schema}.db")
        record = {"ledger": ledger, "seq": seq, "title": title, "session": str(sid or ""), "reason": reason, "at": at,
                  "commit": commit, "schema": schema, "mark": mark_of(con), **({"plan": plan} if plan else {}),
                  **(where or {})}
        note(con, EXPORT, title, seq, json.dumps(record, sort_keys=True), sid, at)
        return record
    return port.write(change)


def saved(port: PlanStore) -> Optional[SavedCopy]:
    """{seq, title, file_id, mark, at} of the newest copy the store holds, or None.

    Args:
        port: the harness ledger (plans, tickets, audit rows).

    Returns:
        The newest uploaded copy (SavedCopy), its mark from its export record (zeros when lost); None when none is.
    """
    for row in port.rows(NEWEST, (UPLOADED,)):
        made = port.rows("SELECT text FROM pl_notes WHERE kind = ? AND key = ? ORDER BY at DESC, rowid DESC LIMIT 1",
                         (EXPORT, row["key"]))
        record = json.loads(made[0]["text"]) if made else {}
        return {"seq": int(row["key"]), "title": row["target"], "file_id": row["text"], "at": row["at"],
                "mark": record.get("mark") or [0] * len(COUNTED)}
    return None


def unsaved(port: PlanStore) -> list[str]:
    """What the store does not hold yet, in words: ['2 commit(s)', '1 plan event(s)']; [] when nothing waits.

    Args:
        port: the harness ledger (plans, tickets, audit rows).

    Returns:
        One "<n> <name>(s)" per count of the mark that is ahead of the newest saved copy's.
    """
    held = (saved(port) or {}).get("mark") or [0] * len(COUNTED)
    return [f"{now - then} {name}(s)" for (name, _), now, then in zip(COUNTED, mark(port), held) if now > then]


def owed(port: PlanStore) -> list[str]:
    """What a turn's end is held for: the unsaved work, unless a turn was already held for exactly this work.

    Args:
        port: the harness ledger (plans, tickets, audit rows).

    Returns:
        The words of unsaved(), or [] when nothing waits or the newest store.asked row holds the mark of now.
    """
    words = unsaved(port)
    if not words:
        return []
    asked = port.rows(NEWEST, (ASKED,))
    return [] if asked and asked[0]["key"] == json.dumps(mark(port)) else words


def asked(port: PlanStore, sid: str) -> None:
    """A turn was held for the work the ledger holds now: keep a store.asked row with the mark of now.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        sid: the Claude Code session id whose turn was held.
    """
    key = json.dumps(mark(port))
    port.write(lambda con, rec: note(con, ASKED, "turn", key, "", sid, int(time.time() * 1000)))


def uploaded(port: PlanStore, event: Event) -> list[str]:
    """Keep that the store holds a copy, when an MCP tool's create_file answered with a file of a copy's name; the
    note for the model. Anything else (another file, an answer without the file) keeps nothing. The server is not
    told by its name: Claude Code names a connector's tools by its name (mcp__Google_Drive__create_file) or by an id
    (mcp__caaed075-...__create_file); a copy's name is its own, so the name of the file is what tells.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        event: the PostToolUse hook call; its tool, input title and response are read.

    Returns:
        ["The store holds copy <seq> of this ledger: <title>."] when the answer holds a copy's file; else [].
    """
    parts = str(event.tool or "").split("__")
    if len(parts) < 3 or parts[0] != "mcp" or parts[-1] != "create_file":
        return []
    title = str((event.input or {}).get("title") or "")
    name = title[:-3] if title.endswith(".db.gz") else title  # a gzipped copy (export.py) is the copy of its name
    made = port.rows("SELECT key FROM pl_notes WHERE kind = ? AND target = ?", (EXPORT, name)) if title else []
    answer = event.response if isinstance(event.response, str) else json.dumps(event.response, ensure_ascii=False)
    found = FILE_ID.search(answer or "")
    if not found or not re.search(r'\\*"title\\*"\s*:\s*\\*"' + re.escape(title), answer or ""):
        return []
    if not made:
        return ticket_uploaded(port, event, title, found.group(1))
    seq = made[0]["key"]
    if not port.rows("SELECT 1 AS x FROM pl_notes WHERE kind = ? AND key = ?", (UPLOADED, seq)):
        port.write(lambda con, rec: note(con, UPLOADED, title, seq, found.group(1), event.session,
                                         int(time.time() * 1000)))
    return [f"The store holds copy {seq} of this ledger: {title}."]


def keep_ticket(port: PlanStore, sid: str, title: str, sha256: str, path: str) -> None:
    """Keep that the harness made a ticket file, so the hook knows its upload.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        sid: the session that made it.
        title: its file name.
        sha256: the hash of its bytes.
        path: where it is on this machine.
    """
    port.write(lambda con, rec: note(con, TICKET, title, sha256, path, sid, int(time.time() * 1000)))


def ticket_uploaded(port: PlanStore, event: Event, title: str, file_id: str) -> list[str]:
    """Keep that the store holds a ticket file the harness made, when Drive answered its create_file with it.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        event: the PostToolUse hook call.
        title: the file name the call gave.
        file_id: the Drive id in the answer.

    Returns:
        ["The store holds the ticket file <title>."] when it is a ticket file the harness made; else [].
    """
    if not port.rows("SELECT 1 AS x FROM pl_notes WHERE kind = ? AND target = ?", (TICKET, title)):
        return []
    if not ticket_held(port, title):
        port.write(lambda con, rec: note(con, TICKET_UP, title, file_id, file_id, event.session,
                                         int(time.time() * 1000)))
    return [f"The store holds the ticket file {title} (Drive file {file_id})."]


def ticket_held(port: PlanStore, title: str) -> str:
    """The Drive id of an uploaded ticket file.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        title: its file name.

    Returns:
        The id; "" when the store does not hold it yet.
    """
    rows = port.rows("SELECT text FROM pl_notes WHERE kind = ? AND target = ? ORDER BY at DESC LIMIT 1", (TICKET_UP, title))
    return rows[0]["text"] if rows else ""


def place(port: PlanStore, name: str) -> str:
    """The Drive id of a subfolder of the store (db or tickets), as a Drive answer showed it under the store folder.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        name: db or tickets.

    Returns:
        Its id; "" when no answer showed it yet, or no store folder is set.
    """
    rows = port.rows("SELECT text FROM pl_notes WHERE kind = ? AND target = ? AND key = ? ORDER BY at DESC, rowid DESC "
                     "LIMIT 1", (FOLDER, name, folder())) if folder() else []
    return rows[0]["text"] if rows else ""


def find_or_make(name: str, root: str) -> str:
    """The words of the Drive calls that find a subfolder of the store, or make it when Drive has none.

    Args:
        name: db or tickets.
        root: the store folder's id.

    Returns:
        The text for the model.
    """
    return (f"First find the store's {name} folder: search_files with the query: title = '{name}' and mimeType = "
            f"'{FOLDER_MIME}' and parentId = '{root}'. If Drive lists none, make it: create_file with title {name}, "
            f"contentMimeType {FOLDER_MIME}, parentId {root}. The harness reads Drive's answer and keeps the folder's "
            f"id; that id is the parentId below.")


def folder_entries(answer: object) -> list[dict[str, object]]:
    """Each object of a Drive answer that has an id and a title (or name), at any depth; a JSON text is read.

    Args:
        answer: the tool's response.

    Returns:
        The objects, in order.
    """
    if isinstance(answer, str):
        try:
            answer = json.loads(answer)
        except ValueError:
            return []
    out = []
    if isinstance(answer, dict):
        if isinstance(answer.get("id"), str) and isinstance(answer.get("title") or answer.get("name"), str):
            out.append(answer)
        for value in answer.values():
            out += folder_entries(value)
    elif isinstance(answer, list):
        for value in answer:
            out += folder_entries(value)
    return out


def placed(port: PlanStore, event: Event) -> list[str]:
    """Keep the id of a subfolder of the store (db or tickets) that a Drive tool's answer shows: a folder of that name
    whose parent is the store folder (its parentId or parents), or listed by a call that names the store folder.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        event: the PostToolUse hook call of an MCP tool; its input and response are read.

    Returns:
        A note per subfolder newly kept.
    """
    root = folder()
    if not root or not str(event.tool or "").startswith("mcp__") or event.kind != "PostToolUse":
        return []
    asked = json.dumps(event.input or {}, ensure_ascii=False)
    found = {}
    for entry in folder_entries(event.response):
        name, parents = entry.get("title") or entry.get("name"), entry.get("parents")
        parent = entry.get("parentId") or (parents[0] if isinstance(parents, list) and parents else None)
        if name in PLACES and entry.get("mimeType") == FOLDER_MIME and (parent == root or (not parent and root in asked)):
            found[str(name)] = str(entry["id"])
    news = {n: i for n, i in found.items() if place(port, n) != i}
    at = int(time.time() * 1000)
    if news:
        port.write(lambda con, rec: [note(con, FOLDER, n, root, i, event.session, at) for n, i in news.items()])
    return [f"The store's {n} folder is Drive folder {i}." for n, i in news.items()]


def status(port: PlanStore) -> str:
    """The store as the ledger knows it, a line each: the folder, the ledger, the newest copy, what waits.

    Args:
        port: the harness ledger (plans, tickets, audit rows).

    Returns:
        Five lines of text for the model.
    """
    ledger = port.rows("SELECT key FROM pl_notes WHERE kind = ? ORDER BY at, rowid LIMIT 1", (LEDGER,))
    made, held, waits = port.rows(NEWEST, (EXPORT,)), saved(port), unsaved(port)
    return "\n".join([
        f"Store folder: {'set' if folder() else 'not set (' + ENV + ')'}.",
        f"Ledger: {ledger[0]['key'] if ledger else 'no copy made yet'}.",
        f"Newest copy made: {made[0]['key'] + ' - ' + made[0]['target'] if made else 'none'}.",
        f"Newest copy in the store: {str(held['seq']) + ' - ' + held['title'] + ' (Drive file ' + held['file_id'] + ')' if held else 'none'}.",
        f"Not in the store yet: {', '.join(waits) if waits else 'nothing'}."])
