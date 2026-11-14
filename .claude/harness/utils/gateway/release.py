"""Releases (blue/green): sessions run a published copy of the harness code, state/live/<sha>/, never the work tree a
session edits; state/live/current names the one in force. A release is the code folders (harness, entry, nets, tests)
as they stand, named by the sha of their content. Building writes the copy; publishing switches current, which only
the user's word allows (cli_live.py). Writing state/ is never a session's: the gates refuse it."""
import hashlib
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

CODE = ("harness", "entry", "nets", "tests")
SKIP = ("__pycache__",)
ALLOW_LABEL, NO_LABEL = "Cho ph\u00e9p", "Kh\u00f4ng"
QUESTION = re.compile("^Cho ph\u00e9p ph\u00e1t h\u00e0nh harness (?P<sha>[0-9a-f]{12})\\?$")


def code_files(code_dir):
    root = Path(code_dir)
    for top in CODE:
        for path in sorted((root / top).rglob("*")):
            if path.is_file() and not any(part in SKIP for part in path.parts):
                yield path.relative_to(root).as_posix(), path


def stamp(code_dir):
    """The sha (12 hex) of the code as it stands: every code file's path and bytes."""
    h = hashlib.sha256()
    for rel, path in code_files(code_dir):
        h.update(rel.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()[:12]


def live_dir(home):
    return Path(home) / "state" / "live"


def release_dir(home, sha):
    return live_dir(home) / sha


def build(home):
    """Copy the work tree's code of home into a release (once per sha); its sha."""
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


def current(home):
    """The sha of the release in force, or None (no release yet, or one that is gone)."""
    try:
        sha = (live_dir(home) / "current").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return sha if (release_dir(home, sha) / "harness").is_dir() else None


def publish(home, sha):
    """Put the release sha in force (one atomic rename)."""
    tmp = live_dir(home) / f".current-{os.getpid()}"
    tmp.write_text(sha, encoding="utf-8")
    os.replace(tmp, live_dir(home) / "current")


def accepts(port, answers):
    """Keep the user's Cho ph\u00e9p to a publish form as a one-use pass of exactly that sha (cli_live.py spends it)."""
    notes = []
    for q, label in (answers or {}).items():
        m = QUESTION.match(str(q))
        if m and str(label).strip() == ALLOW_LABEL:
            port.write(lambda con, rec, sha=m["sha"]: con.execute(
                "INSERT OR REPLACE INTO pl_asks (sid, key, at, used) VALUES ('', ?, ?, 0)",
                (f"live-publish:{sha}", int(time.time() * 1000))))
            notes.append(f"GATE: the user allows publishing release {m['sha']}; run live publish again, once.")
    return notes
