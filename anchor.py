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
installed, the repository's own is the core.

The fallback, so a broken release never locks a session: a release whose hook crashes (it raises, or says so with
HARNESS_HOOK_FAILED) is tried once more, then left for the previous release (state/live/previous), which is put in
force; the broken one is listed in state/live/bad, which no update puts back. The entry fallback is an MCP server of
this file alone (tools rollback, status) that never loads a release; the hook lets its calls pass, so a release that
refuses everything can still be rolled back. One step back only: previous is cleared by a fall back."""
from __future__ import annotations

import io
import json
import os
import re
import runpy
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

HOME = Path(__file__).resolve().parent / ".claude"
ENTRIES = ("hook", "mcp_server", "doctor", "cli", "session_start", "fallback")
CRASHED = "HARNESS_HOOK_FAILED"  # a release's hook sets it when it failed rather than refused
FALLBACK_TOOLS = "mcp__fallback__"  # the calls of this file's own server: never judged by a release
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


def live_text(name: str) -> str:
    """One file of state/live/ (current, previous, bad), stripped; "" when it is not there.

    Args:
        name: the file's name.

    Returns:
        Its text, or "".
    """
    try:
        return (HOME / "state" / "live" / name).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def set_live(name: str, text: str) -> None:
    """Write one file of state/live/ in one atomic rename.

    Args:
        name: the file's name.
        text: its whole text.
    """
    tmp = HOME / "state" / "live" / f".{name}-{os.getpid()}"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, HOME / "state" / "live" / name)


def roll_back(why: str) -> tuple[bool, str]:
    """Put the previous release in force, list the current one as bad, clear previous and log why.

    Args:
        why: the reason, kept in state/live/fallback.log.

    Returns:
        (whether it rolled back, the text for the caller).
    """
    now, back = live_text("current"), live_text("previous")
    if not back or not (HOME / "state" / "live" / back / "harness").is_dir():
        return False, f"No previous release to go back to; release {now or 'none'} stays in force."
    set_live("bad", "\n".join(sorted(set(live_text("bad").split()) | {now})) + "\n")
    set_live("current", back)
    set_live("previous", "")
    with open(HOME / "state" / "live" / "fallback.log", "a", encoding="utf-8") as log:
        log.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {now} -> {back}: {why}\n")
    return True, (f"Release {back} is in force again; release {now} is marked bad and no update puts it back. "
                  f"Fix main with a new pull request.")


def run_entry(name: str, args: list[str], stdin: Optional[bytes] = None) -> tuple[int, bool]:
    """Run an entry of the release in force in this process.

    Args:
        name: the entry.
        args: its arguments.
        stdin: the bytes it reads on stdin (a hook's payload, read once by the anchor), or None for the real stdin.

    Returns:
        (its exit code, whether it crashed rather than answered).
    """
    code = code_dir(HOME)
    os.environ["HARNESS_HOME"], os.environ["HARNESS_CODE"] = str(HOME), str(code)
    os.environ.pop(CRASHED, None)
    for module in [m for m in sys.modules if m == "harness" or m.startswith("harness.")]:
        del sys.modules[module]  # a second run must import the other release's code, not this one's
    if stdin is not None:
        sys.stdin = io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")
    sys.argv = [str(entry_file(code, name))] + args
    try:
        runpy.run_path(sys.argv[0], run_name="__main__")
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else (0 if e.code is None else 2)
        return exit_code, exit_code == 2 and bool(os.environ.get(CRASHED))
    except BaseException as e:
        sys.stderr.write(f"anchor: release {code.name} failed: {type(e).__name__}: {e}\n")
        return 2, True
    return 0, False


def hook(args: list[str]) -> int:
    """A hook call: the fallback's own calls pass; a crash is tried once more, then falls back to the previous release.

    Args:
        args: the hook's arguments.

    Returns:
        The exit code for Claude Code.
    """
    raw = sys.stdin.buffer.read()
    try:
        tool = str(json.loads(raw or b"{}").get("tool_name") or "")
    except (ValueError, AttributeError):
        tool = ""
    if tool.startswith(FALLBACK_TOOLS):
        return 0  # the way out of a broken release is never judged by it
    code, crashed = run_entry("hook", args, raw)
    if crashed:
        code, crashed = run_entry("hook", args, raw)  # once more: a passing fault is no reason to leave a release
    if crashed:
        broken = live_text("current")
        done, text = roll_back(f"the hook of release {broken} crashed twice")
        if done:
            sys.stderr.write(f"anchor: fell back. {text}\n")
            code, _ = run_entry("hook", args, raw)
    return code


TOOLS = [{"name": "rollback", "description": "Put the previous harness release in force when the new one is broken "
          "(it refuses or blocks every call). The broken one is marked bad and no update puts it back.",
          "inputSchema": {"type": "object", "properties": {"why": {"type": "string"}}, "required": []}},
         {"name": "status", "description": "Which harness release is in force, the previous one and the bad ones.",
          "inputSchema": {"type": "object", "properties": {}, "required": []}}]


def fallback_answer(request: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The answer of the fallback MCP server to one JSON-RPC request; None for a notification.

    Args:
        request: the request ({id, method, params}).

    Returns:
        The JSON-RPC answer, or None when the request has no id.
    """
    if "id" not in request:
        return None
    method, params = request.get("method"), request.get("params") or {}
    result: dict[str, Any]
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion") or "2024-11-05", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "fallback", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call" and params.get("name") == "rollback":
        why = str((params.get("arguments") or {}).get("why") or "asked through the fallback server")[:300]
        done, text = roll_back(why)
        result = {"content": [{"type": "text", "text": text}], "isError": not done}
    elif method == "tools/call" and params.get("name") == "status":
        text = (f"In force: {live_text('current') or 'none'}. Previous: {live_text('previous') or 'none'}. "
                f"Bad: {', '.join(live_text('bad').split()) or 'none'}.")
        result = {"content": [{"type": "text", "text": text}], "isError": False}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32601, "message": f"no method {method}"}}
    return {"jsonrpc": "2.0", "id": request["id"], "result": result}


def fallback() -> int:
    """The fallback MCP server over stdio: one JSON-RPC request a line, until stdin ends.

    Returns:
        0.
    """
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except ValueError:
            continue
        answer = fallback_answer(request) if isinstance(request, dict) else None
        if answer is not None:
            sys.stdout.write(json.dumps(answer) + "\n")
            sys.stdout.flush()
    return 0


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
        if core is not None and name in ("mcp_server", "fallback") and core[0] != HOME:
            return subprocess.call([sys.executable, str(core[1]), name, *args])
        if name == "fallback":
            return fallback()
        if name == "hook":
            return hook(args)
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
