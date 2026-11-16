"""Anchor: the one file Claude Code runs (the hooks of settings.json and the server of .mcp.json name it):
python3 anchor.py <entry> [args], entry one of hook, mcp_server, doctor, cli, session_start. It sits at the root of the
core repository, beside .claude/, and never moves: everything else of the harness is under .claude/harness/ and may
change with a release. It routes the call to that entry of the release in force (.claude/state/live/current), its
harness/entry/<entry>.py, never to the work tree a session edits; with no release yet, to the work tree's own. The
entry is told the home (the .claude folder: state, config) and the code it runs (HARNESS_HOME, HARNESS_CODE). Any
failure exits 2, which blocks a hook's call. Standard library only: this file is the trust anchor, and no session may
write it.

One core: a repository's own wiring (.claude/settings.json, .mcp.json) calls the anchor with --project. When a harness
is installed for the user (harness/entry/install.py: the hooks of ~/.claude/settings.json name its anchor.py), that
one is the core and this call gives way: a hook does nothing (the core's own hook judges the call), the MCP server is
the core's. So a clone of the harness being worked on is never a second harness with a second ledger; with no harness
installed, the repository's own is the core."""
from __future__ import annotations

import json
import os
import re
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Optional

HOME = Path(__file__).resolve().parent / ".claude"
ENTRIES = ("hook", "mcp_server", "doctor", "cli", "session_start")
PROJECT = "--project"  # how a repository's own wiring calls the anchor
# the hook command install writes: "<python>" "<core>/anchor.py" hook (before the anchor: .claude/entry/boot.py)
CORE_HOOK = re.compile(r'"([^"$%]+[\\/](?:anchor\.py|entry[\\/]boot\.py))" hook\b')


def code_dir(home: Path) -> Path:
    """The release in force, or the home itself when none is published.

    Args:
        home: the .claude folder beside this file.

    Returns:
        state/live/<sha> of the release in force when it holds a harness, else home.
    """
    try:
        sha = (home / "state" / "live" / "current").read_text(encoding="utf-8").strip()
    except OSError:
        return home
    release = home / "state" / "live" / sha
    return release if sha and (release / "harness").is_dir() else home


def entry_file(code: Path, name: str) -> Path:
    """The entry of a code folder: harness/entry/<name>.py; a release built before the entries moved keeps entry/.

    Args:
        code: the code folder (a release, or the home).
        name: the entry (hook, mcp_server, doctor, cli, session_start).

    Returns:
        The path of the entry script.
    """
    moved = code / "harness" / "entry" / f"{name}.py"
    return moved if moved.is_file() else code / "entry" / f"{name}.py"


def installed_core() -> Optional[tuple[Path, Path]]:
    """(home, script) of the harness installed for this user: what a hook of the user's settings names, when that file
    is there; else None (nothing installed, or settings that cannot be read: this copy then guards).

    Returns:
        (the installed harness's .claude folder, its anchor or legacy boot.py), or None.
    """
    folder = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    try:
        data = json.loads(Path(folder, "settings.json").read_text(encoding="utf-8"))
        commands = [h["command"] for groups in data["hooks"].values() for g in groups for h in g["hooks"]]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    for command in commands:
        found = CORE_HOOK.search(str(command))
        if found and Path(found.group(1)).is_file():
            script = Path(found.group(1)).resolve()
            return (script.parent / ".claude" if script.name == "anchor.py" else script.parent.parent), script
    return None


def main() -> int:
    """Route the call to the entry of the release in force (or give way to the installed core).

    Returns:
        The exit code: the entry's (its SystemExit code), 0 when it ends without one or gives way, 2 when it fails.
    """
    try:
        name = sys.argv[1] if len(sys.argv) > 1 else ""
        if name not in ENTRIES:
            sys.stderr.write(f"anchor: the entry is one of {', '.join(ENTRIES)}\n")
            return 2
        args = [a for a in sys.argv[2:] if a != PROJECT]
        core = installed_core() if PROJECT in sys.argv[2:] else None
        if core is not None and name == "hook":
            return 0  # the installed harness's own hook judges this call
        if core is not None and name == "mcp_server" and core[0] != HOME:
            return subprocess.call([sys.executable, str(core[1]), name, *args])
        code = code_dir(HOME)
        os.environ["HARNESS_HOME"], os.environ["HARNESS_CODE"] = str(HOME), str(code)
        sys.argv = [str(entry_file(code, name))] + args
        runpy.run_path(sys.argv[0], run_name="__main__")
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 2)
    except BaseException as e:
        sys.stderr.write(f"anchor failed, the call is blocked: {type(e).__name__}: {e}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
