"""Export: a whole copy of the ledger, to hand to a store outside the machine (a cloud machine's ledger is lost with
it). The copy is made with SQLite's own backup, so a ledger in use copies whole; it is kept only when its schema is
exactly the one schema.sql gives, so every copy a store holds reads the same way. Its name and its record inside the
ledger are the store's (store.py): <session>__<ledger>-<number>__<UTC time>__<reason>__<newest commit>__s<schema>.db.
Copies with the same last part have the same schema. An older copy of the same session in the folder is taken away.
The file uploaded is that copy gzipped, <name>.db.gz: one Drive connector call carries about 3 MB of file, and the
ledger grows past that; a gzipped copy still over MOST bytes is refused with its size.

The copy goes to <the session's working folder>/.harness-export/: the Drive tool reads a file by reference only from
the folders a session works in (a temp folder is refused). The folder ignores itself for git (its own .gitignore), so
a copy is never committed with the work."""
from __future__ import annotations

import gzip
import hashlib
import re
import shutil
import sqlite3
from pathlib import Path

from harness.utils.ledger.db import LedgerError, fingerprint, pinned
from harness.utils.ledger.store import find_or_make, session_part
from harness.utils.shapes import ExportCopy, StoreRecord

FOLDER_ID = re.compile(r"^[A-Za-z0-9_-]{10,}$")
MIME = "application/gzip"
FOLDER = ".harness-export"
GZ = ".gz"
MOST = 3_000_000  # bytes of a gzipped copy one Drive connector call carries (its limit is about 3.1 MB of files)


def snapshot(db_path: str | Path, out_dir: str | Path, record: StoreRecord) -> ExportCopy:
    """{path, title, sha256, size} of a new gzipped copy of the ledger db_path in out_dir, named by the store's record
    {title, session} with .gz; LedgerError when there is no ledger, the copy's schema is not the pinned one, or the
    gzipped copy is over MOST bytes (the copy is then taken away).

    Args:
        db_path: the live ledger's file.
        out_dir: the folder the copy goes to (made, with a .gitignore of "*", when missing).
        record: the store's record of the copy (store.begin); its title and session are read.

    Returns:
        The copy (ExportCopy): title <record title>.gz, the hash and size of the gz file; an older copy of the same
        session in out_dir is taken away.

    Raises:
        LedgerError: there is no ledger, it cannot be copied, its schema is not the pinned one, or it is too big.
    """
    db_path, out_dir = Path(db_path), Path(out_dir)
    if not db_path.is_file():
        raise LedgerError("there is no ledger yet: nothing to export")
    out_dir.mkdir(parents=True, exist_ok=True)
    if not (out_dir / ".gitignore").exists():
        (out_dir / ".gitignore").write_text("*\n", encoding="utf-8")  # git never sees a copy
    session = session_part(record.get("session"))
    work = out_dir / f"{session}.copying"
    work.unlink(missing_ok=True)
    src = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    dst, same = sqlite3.connect(work), False
    try:
        src.backup(dst)
        same = fingerprint(dst) == pinned()
    except sqlite3.Error as e:
        raise LedgerError(f"the ledger could not be copied ({type(e).__name__}: {e})") from e
    finally:
        dst.close()
        src.close()
        if not same:
            work.unlink(missing_ok=True)
    if not same:
        raise LedgerError("the ledger's schema is not the harness's (schema.sql): it is not exported")
    for old in [*out_dir.glob(f"{session}__*.db"), *out_dir.glob(f"{session}__*.db{GZ}")]:
        old.unlink()
    path = out_dir / (record["title"] + GZ)
    try:
        with open(work, "rb") as raw, gzip.open(path, "wb", compresslevel=9) as packed:
            shutil.copyfileobj(raw, packed)
    finally:
        work.unlink(missing_ok=True)
    data = path.read_bytes()
    if len(data) > MOST:
        path.unlink()
        raise LedgerError(f"the copy is {len(data)} bytes gzipped, over the {MOST} one Drive call carries: it is not "
                          "uploaded; tell the user")
    return {"path": path.resolve().as_posix(), "title": path.name, "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data)}


def upload_call(copy: ExportCopy, folder: str, db: str = "") -> str:
    """The words of the one Drive call that uploads a copy into the store's db folder (a file reference: the app reads
    the file); when the db folder is not known yet, first the calls that find or make it.

    Args:
        copy: the copy snapshot() made.
        folder: the store folder's Drive id.
        db: the store's db folder's Drive id (store.place); "" when no Drive answer showed it yet.

    Returns:
        The text for the model: the create_file arguments to send, and what to do when it cannot.
    """
    first = "" if db else find_or_make("db", folder) + "\n"
    return (f"Exported the ledger: {copy['title']} ({copy['size']} bytes).\n" + first +
            "Upload it now, once, with the Google Drive tool create_file, exactly:\n"
            f"  title: {copy['title']}\n  parentId: {db or '<the id of the db folder Drive gave>'}\n"
            f"  contentMimeType: {MIME}\n"
            f"  disableConversionToGoogleType: true\n"
            f"  base64Content: sha256:{copy['sha256']}:{copy['path']}\n"
            "The store only grows: never change, move or trash a file in it. With no Google Drive tool in this "
            "session, tell the user the copy was not uploaded. If Drive answers that the file cannot be sent by "
            "reference, export again with {into: '<a folder inside this session's working folder>'}.")
