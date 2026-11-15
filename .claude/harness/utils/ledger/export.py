"""Export: a whole copy of the ledger, to hand to a store outside the machine (a cloud machine's ledger is lost with
it). The copy is made with SQLite's own backup, so a ledger in use copies whole; it is kept only when its schema is
exactly the one schema.sql gives, so every copy a store holds reads the same way. The copy is named
<session>__<UTC time>__<newest commit, 7 characters, or nocommit>__s<the schema's fingerprint, 8 characters>.db: copies
with the same last part have the same schema. An older copy of the same session in the folder is taken away.

The copy goes to <the session's working folder>/.harness-export/: the Drive tool reads a file by reference only from
the folders a session works in (a temp folder is refused). The folder ignores itself for git (its own .gitignore), so
a copy is never committed with the work."""
import hashlib
import re
import sqlite3
import time
from pathlib import Path

from harness.utils.ledger.db import LedgerError, fingerprint, pinned

FOLDER_ID = re.compile(r"^[A-Za-z0-9_-]{10,}$")
MIME = "application/x-sqlite3"
FOLDER = ".harness-export"


def session_part(sid):
    return re.sub(r"[^A-Za-z0-9-]", "-", str(sid or "")).strip("-") or "nosession"


def newest_commit(con):
    row = con.execute("SELECT commit_sha FROM rec_commits ORDER BY at DESC, rowid DESC LIMIT 1").fetchone()
    return str(row[0])[:7] if row and row[0] else "nocommit"


def snapshot(db_path, out_dir, sid, now=None):
    """{path, title, sha256, size, schema, commit} of a new copy of the ledger db_path in out_dir; LedgerError when
    there is no ledger, or the copy's schema is not the pinned one (the copy is then taken away)."""
    db_path, out_dir = Path(db_path), Path(out_dir)
    if not db_path.is_file():
        raise LedgerError("there is no ledger yet: nothing to export")
    out_dir.mkdir(parents=True, exist_ok=True)
    if not (out_dir / ".gitignore").exists():
        (out_dir / ".gitignore").write_text("*\n", encoding="utf-8")  # git never sees a copy
    session = session_part(sid)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
    work = out_dir / f"{session}.copying"
    work.unlink(missing_ok=True)
    src = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    dst = sqlite3.connect(work)
    try:
        src.backup(dst)
        commit = newest_commit(dst) if fingerprint(dst) == pinned() else None
    except sqlite3.Error as e:
        raise LedgerError(f"the ledger could not be copied ({type(e).__name__}: {e})") from e
    finally:
        dst.close()
        src.close()
        if "commit" not in locals() or commit is None:
            work.unlink(missing_ok=True)
    if commit is None:
        raise LedgerError("the ledger's schema is not the harness's (schema.sql): it is not exported")
    for old in out_dir.glob(f"{session}__*.db"):
        old.unlink()
    title = f"{session}__{stamp}__{commit}__s{pinned()[:8]}.db"
    path = out_dir / title
    work.replace(path)
    data = path.read_bytes()
    return {"path": path.resolve().as_posix(), "title": title, "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data), "schema": f"s{pinned()[:8]}", "commit": commit}


def upload_call(copy, folder):
    """The words of the one Drive call that uploads a copy to the folder (a file reference: the app reads the file)."""
    return (f"Exported the ledger: {copy['title']} ({copy['size']} bytes, schema {copy['schema']}, newest commit "
            f"{copy['commit']}).\nUpload it now, once, with the Google Drive tool create_file, exactly:\n"
            f"  title: {copy['title']}\n  parentId: {folder}\n  contentMimeType: {MIME}\n"
            f"  disableConversionToGoogleType: true\n"
            f"  base64Content: sha256:{copy['sha256']}:{copy['path']}\n"
            "The store only grows: never change, move or trash a file in it. With no Google Drive tool in this "
            "session, tell the user the copy was not uploaded. If Drive answers that the file cannot be sent by "
            "reference, export again with {into: '<a folder inside this session's working folder>'}.")
