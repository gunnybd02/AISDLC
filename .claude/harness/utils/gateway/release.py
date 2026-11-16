"""Releases (blue/green): sessions run a published copy of the harness code, state/live/<sha>/, never the work tree a
session edits; state/live/current names the one in force. A release is the code folders (harness: its blocks, entries, nets and tests; entry: forwarders of the old paths)
as they stand, named by the sha of their content. Building writes the copy; publishing switches current, which only
the user's word allows (cli_live.py). Writing state/ is never a session's: the gates refuse it."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Optional

from harness.utils.shapes import PlanStore

CODE = ("harness", "entry")


def anchor(home: str | Path) -> Path:
    """The anchor of a home: anchor.py beside its .claude folder, the one file Claude Code runs.

    Args:
        home: the harness home (the .claude folder).

    Returns:
        The path of anchor.py beside it (it may not exist).
    """
    return Path(home).resolve().parent / "anchor.py"


def entry_of(code: str | Path, name: str) -> Path:
    """An entry of a code folder: harness/entry/<name>.py (a release built before the entries moved: entry/).

    Args:
        code: a code folder (a release, or the home's work tree).
        name: the entry's name (hook, mcp_server, cli...).

    Returns:
        harness/entry/<name>.py when it is a file, else entry/<name>.py (which may not exist).
    """
    moved = Path(code) / "harness" / "entry" / f"{name}.py"
    return moved if moved.is_file() else Path(code) / "entry" / f"{name}.py"
SKIP = ("__pycache__",)
ALLOW_LABEL, NO_LABEL = "Allow", "Deny"
QUESTION = re.compile("^Allow publishing harness release (?P<sha>[0-9a-f]{12})\\?$")


def code_files(code_dir: str | Path) -> Iterator[tuple[str, Path]]:
    """Every code file of a code folder: the files under CODE, __pycache__ left out, sorted per folder.

    Args:
        code_dir: the code folder (a home or a release).

    Returns:
        An iterator of (path from code_dir with forward slashes, the file's path).
    """
    root = Path(code_dir)
    for top in CODE:
        for path in sorted((root / top).rglob("*")):
            if path.is_file() and not any(part in SKIP for part in path.parts):
                yield path.relative_to(root).as_posix(), path


def stamp(code_dir: str | Path) -> str:
    """The sha (12 hex) of the code as it stands: every code file's path and bytes.

    Args:
        code_dir: the code folder (a home or a release).

    Returns:
        12 hex characters of the sha256.
    """
    h = hashlib.sha256()
    for rel, path in code_files(code_dir):
        h.update(rel.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()[:12]


def live_dir(home: str | Path) -> Path:
    """The folder of the releases of a home.

    Args:
        home: the harness home.

    Returns:
        <home>/state/live.
    """
    return Path(home) / "state" / "live"


def release_dir(home: str | Path, sha: str) -> Path:
    """The folder of one release.

    Args:
        home: the harness home.
        sha: the release's sha (stamp).

    Returns:
        <home>/state/live/<sha>.
    """
    return live_dir(home) / sha


def build(home: str | Path) -> str:
    """Copy the work tree's code of home into a release (once per sha); its sha.

    Args:
        home: the harness home whose work tree is copied.

    Returns:
        The release's sha; the copy is made in a temp folder and renamed into place.
    """
    sha = stamp(home)
    target = release_dir(home, sha)
    if not (target / "harness").is_dir():
        live_dir(home).mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".{sha}-", dir=live_dir(home)))
        for rel, path in code_files(home):
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, tmp / rel)
        if target.exists():
            shutil.rmtree(target)
        os.replace(tmp, target)
    return sha


def current(home: str | Path) -> Optional[str]:
    """The sha of the release in force, or None (no release yet, or one that is gone).

    Args:
        home: the harness home.

    Returns:
        The sha state/live/current names when that release is there, else None.
    """
    try:
        sha = (live_dir(home) / "current").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return sha if (release_dir(home, sha) / "harness").is_dir() else None


def publish(home: str | Path, sha: str) -> None:
    """Put the release sha in force (one atomic rename).

    Args:
        home: the harness home.
        sha: the release to put in force.
    """
    tmp = live_dir(home) / f".current-{os.getpid()}"
    tmp.write_text(sha, encoding="utf-8")
    os.replace(tmp, live_dir(home) / "current")


def accepts(port: PlanStore, answers: dict[str, str]) -> list[str]:
    """Keep the user's Allow to a publish form as a one-use pass of exactly that sha (cli_live.py spends it).

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        answers: {form question: the label the user chose} of an AskUserQuestion call.

    Returns:
        One GATE note per publish question answered Allow; [] when none was.
    """
    notes = []
    for q, label in (answers or {}).items():
        m = QUESTION.match(str(q))
        if m and str(label).strip() == ALLOW_LABEL:
            port.write(lambda con, rec, sha=m["sha"]: con.execute(
                "INSERT OR REPLACE INTO pl_asks (sid, key, at, used) VALUES ('', ?, ?, 0)",
                (f"live-publish:{sha}", int(time.time() * 1000))))
            notes.append(f"GATE: the user allows publishing release {m['sha']}; run live publish again, once.")
    return notes
