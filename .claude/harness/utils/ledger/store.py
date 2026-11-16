"""Store: what a ledger knows of its copies outside the machine (a Google Drive folder; export.py makes a copy). It is
kept as rows of pl_notes, so the schema stays the pinned one and every copy carries its own story:

  store.ledger    key = the ledger's id, given once: a ledger that starts again on a new machine is another ledger
  store.export    key = the copy's number, target = its file name, text = who and when (ledger, seq, session, reason,
                  at, commit, repo, branch, harness, mark); written before the copy is made, so the copy holds it
  store.uploaded  key = the copy's number, target = its file name, text = the Drive file's id; written when the
                  hook sees the Drive tool answer with that file
  store.asked     key = the mark a turn was held for, so a turn is held once for the same work

The mark counts what must not be lost: commits, plan events (approved, delivered, dropped), pushes and merge requests.
Work is unsaved while the mark is ahead of the mark of the newest copy the store holds. Small rows (verify receipts,
logs) wait for the next copy. The folder's id is the environment variable HARNESS_DRIVE_FOLDER: never in the tree."""
import json
import os
import re
import time
import uuid

from harness.utils.ledger.db import pinned

ENV = "HARNESS_DRIVE_FOLDER"
REASONS = ("manual", "push", "plan-close", "turn-end")
LEDGER, EXPORT, UPLOADED, ASKED = "store.ledger", "store.export", "store.uploaded", "store.asked"
COUNTED = (("commit", "SELECT COUNT(*) AS n FROM rec_commits"),
           ("plan event", "SELECT COUNT(*) AS n FROM pl_plan_events WHERE event IN ('approved', 'delivered', 'dropped')"),
           ("push or merge request", "SELECT COUNT(*) AS n FROM pl_git_audit"))
NEWEST = "SELECT key, target, text, at FROM pl_notes WHERE kind = ? ORDER BY at DESC, rowid DESC LIMIT 1"
FILE_ID = re.compile(r'\\*"id\\*"\s*:\s*\\*"([A-Za-z0-9_-]{10,})')


def folder():
    return os.environ.get(ENV, "").strip()


def session_part(sid):
    return re.sub(r"[^A-Za-z0-9-]", "-", str(sid or "")).strip("-") or "nosession"


def note(con, kind, target, key, text, sid, at):
    con.execute("INSERT INTO pl_notes (uid, kind, target, key, text, why, sid, at) VALUES (?, ?, ?, ?, ?, '', ?, ?)",
                (uuid.uuid4().hex, kind, target, str(key), text, str(sid or ""), at))


def mark_of(con):
    return [con.execute(sql).fetchone()[0] for _, sql in COUNTED]


def mark(port):
    return [(port.rows(sql) or [{"n": 0}])[0]["n"] for _, sql in COUNTED]


def begin(port, sid, reason, where=None, now=None):
    """Keep the record of a new copy (and the ledger's id, the first time) and answer it: {ledger, seq, title, ...}."""
    seconds = time.time() if now is None else now
    at, stamp = int(seconds * 1000), time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(seconds))

    def change(con, rec):
        row = con.execute("SELECT key FROM pl_notes WHERE kind = ? ORDER BY at, rowid LIMIT 1", (LEDGER,)).fetchone()
        ledger = row[0] if row else uuid.uuid4().hex[:12]
        if not row:
            note(con, LEDGER, "ledger", ledger, "", sid, at)
        seq = 1 + con.execute("SELECT COUNT(*) FROM pl_notes WHERE kind = ?", (EXPORT,)).fetchone()[0]
        last = con.execute("SELECT commit_sha FROM rec_commits ORDER BY at DESC, rowid DESC LIMIT 1").fetchone()
        commit = str(last[0])[:7] if last and last[0] else "nocommit"
        schema = f"s{pinned()[:8]}"
        title = f"{session_part(sid)}__{ledger[:6]}-{seq:03d}__{stamp}__{reason}__{commit}__{schema}.db"
        record = {"ledger": ledger, "seq": seq, "title": title, "session": str(sid or ""), "reason": reason, "at": at,
                  "commit": commit, "schema": schema, "mark": mark_of(con), **(where or {})}
        note(con, EXPORT, title, seq, json.dumps(record, sort_keys=True), sid, at)
        return record
    return port.write(change)


def saved(port):
    """{seq, title, file_id, mark, at} of the newest copy the store holds, or None."""
    for row in port.rows(NEWEST, (UPLOADED,)):
        made = port.rows("SELECT text FROM pl_notes WHERE kind = ? AND key = ? ORDER BY at DESC, rowid DESC LIMIT 1",
                         (EXPORT, row["key"]))
        record = json.loads(made[0]["text"]) if made else {}
        return {"seq": int(row["key"]), "title": row["target"], "file_id": row["text"], "at": row["at"],
                "mark": record.get("mark") or [0] * len(COUNTED)}
    return None


def unsaved(port):
    """What the store does not hold yet, in words: ['2 commit(s)', '1 plan event(s)']; [] when nothing waits."""
    held = (saved(port) or {}).get("mark") or [0] * len(COUNTED)
    return [f"{now - then} {name}(s)" for (name, _), now, then in zip(COUNTED, mark(port), held) if now > then]


def owed(port):
    """What a turn's end is held for: the unsaved work, unless a turn was already held for exactly this work."""
    words = unsaved(port)
    if not words:
        return []
    asked = port.rows(NEWEST, (ASKED,))
    return [] if asked and asked[0]["key"] == json.dumps(mark(port)) else words


def asked(port, sid):
    """A turn was held for the work the ledger holds now."""
    key = json.dumps(mark(port))
    port.write(lambda con, rec: note(con, ASKED, "turn", key, "", sid, int(time.time() * 1000)))


def uploaded(port, event):
    """Keep that the store holds a copy, when a Drive tool's create_file answered with a file of a copy's name; the
    note for the model. Anything else (another file, an answer without the file) keeps nothing."""
    parts = str(event.tool or "").split("__")
    if len(parts) < 3 or parts[0] != "mcp" or "drive" not in parts[1].lower() or parts[-1] != "create_file":
        return []
    title = str((event.input or {}).get("title") or "")
    made = port.rows("SELECT key FROM pl_notes WHERE kind = ? AND target = ?", (EXPORT, title)) if title else []
    answer = event.response if isinstance(event.response, str) else json.dumps(event.response, ensure_ascii=False)
    found = FILE_ID.search(answer or "")
    if not made or not found or not re.search(r'\\*"title\\*"\s*:\s*\\*"' + re.escape(title), answer):
        return []
    seq = made[0]["key"]
    if not port.rows("SELECT 1 AS x FROM pl_notes WHERE kind = ? AND key = ?", (UPLOADED, seq)):
        port.write(lambda con, rec: note(con, UPLOADED, title, seq, found.group(1), event.session,
                                         int(time.time() * 1000)))
    return [f"The store holds copy {seq} of this ledger: {title}."]


def status(port):
    """The store as the ledger knows it, a line each: the folder, the ledger, the newest copy, what waits."""
    ledger = port.rows("SELECT key FROM pl_notes WHERE kind = ? ORDER BY at, rowid LIMIT 1", (LEDGER,))
    made, held, waits = port.rows(NEWEST, (EXPORT,)), saved(port), unsaved(port)
    return "\n".join([
        f"Store folder: {'set' if folder() else 'not set (' + ENV + ')'}.",
        f"Ledger: {ledger[0]['key'] if ledger else 'no copy made yet'}.",
        f"Newest copy made: {made[0]['key'] + ' - ' + made[0]['target'] if made else 'none'}.",
        f"Newest copy in the store: {str(held['seq']) + ' - ' + held['title'] + ' (Drive file ' + held['file_id'] + ')' if held else 'none'}.",
        f"Not in the store yet: {', '.join(waits) if waits else 'nothing'}."])
