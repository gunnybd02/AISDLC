"""Boot: what Claude Code runs (settings.json and .mcp.json name this file): python3 .claude/entry/boot.py <entry>
[args], entry one of hook, mcp_server, doctor, cli, session_start. It runs that entry of the release in force
(state/live/current), never the work tree a session edits; with no release yet, the work tree's own. The entry is told
the home (the real .claude folder: state, config, skills) and the code it runs (HARNESS_HOME, HARNESS_CODE). Any
failure exits 2, which blocks a hook's call. Standard library only: this file is the trust anchor, and no session may
write it.

One core: a repository's own wiring (.claude/settings.json, .mcp.json) calls boot with --project. When a harness is
installed for the user (entry/install.py: the hooks of ~/.claude/settings.json name its boot.py), that one is the
core and this call gives way: a hook does nothing (the core's own hook judges the call), the MCP server is the
core's. So a clone of the harness being worked on is never a second harness with a second ledger; with no harness
installed, the repository's own is the core."""
import json
import os
import re
import runpy
import subprocess
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parent.parent
ENTRIES = ("hook", "mcp_server", "doctor", "cli", "session_start")
PROJECT = "--project"  # how a repository's own wiring calls boot
CORE_HOOK = re.compile(r'"([^"$%]+[\\/]entry[\\/]boot\.py)" hook\b')  # the hook command entry/install.py writes


def installed_core():
    """The home of the harness installed for this user: the boot.py a hook of the user's settings names, when that
    file is there; else None (nothing installed, or settings that cannot be read: this copy then guards)."""
    folder = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    try:
        data = json.loads(Path(folder, "settings.json").read_text(encoding="utf-8"))
        commands = [h["command"] for groups in data["hooks"].values() for g in groups for h in g["hooks"]]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    for command in commands:
        found = CORE_HOOK.search(str(command))
        if found and Path(found.group(1)).is_file():
            return Path(found.group(1)).resolve().parent.parent
    return None


def code_dir(home):
    """The release in force, or the home itself when none is published."""
    try:
        sha = (home / "state" / "live" / "current").read_text(encoding="utf-8").strip()
    except OSError:
        return home
    release = home / "state" / "live" / sha
    return release if sha and (release / "harness").is_dir() else home


def main():
    try:
        name = sys.argv[1] if len(sys.argv) > 1 else ""
        if name not in ENTRIES:
            sys.stderr.write(f"boot: the entry is one of {', '.join(ENTRIES)}\n")
            return 2
        args = [a for a in sys.argv[2:] if a != PROJECT]
        core = installed_core() if PROJECT in sys.argv[2:] else None
        if core is not None and name == "hook":
            return 0  # the installed harness's own hook judges this call
        if core is not None and name == "mcp_server" and core != HOME:
            return subprocess.call([sys.executable, str(core / "entry" / "boot.py"), name, *args])
        code = code_dir(HOME)
        os.environ["HARNESS_HOME"], os.environ["HARNESS_CODE"] = str(HOME), str(code)
        sys.argv = [str(code / "entry" / f"{name}.py")] + args
        runpy.run_path(sys.argv[0], run_name="__main__")
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 2)
    except BaseException as e:
        sys.stderr.write(f"boot failed, the call is blocked: {type(e).__name__}: {e}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
