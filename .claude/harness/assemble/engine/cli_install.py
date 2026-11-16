"""Install the harness for every Claude Code session of a user (harness/entry/install.py): the hooks go into the
user's own settings (~/.claude/settings.json), merged with the hooks already there (SessionStart brings the harness up to date
when a session begins: harness/entry/session_start.py), and the harness's MCP server is registered at
user scope (~/.claude.json mcpServers), so any repository a session works on runs under the harness from its first
prompt. Its own CLI (anchor.py cli ...) is allowed in the user's permissions, so a session in auto mode may run it:
the hooks still judge every call, and a new release still needs the user's word. The harness's home is the .claude
folder of this clone: its ledger, config and releases. Safe to run again; uninstall takes out only what install put in.
Every file is rewritten in one atomic rename. What a machine set up before the anchor holds (hooks, rules and
server naming .claude/entry/boot.py) is taken out first, so nothing runs twice."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from harness.utils.contracts import PERMISSIONS_KEY
from harness.utils.gateway.release import anchor

EVENTS = {"PreToolUse": "*", "PostToolUse": "*", "UserPromptSubmit": None, "Stop": None, "SessionStart": None}
ENTRY = {"SessionStart": "session_start"}  # the entry of the anchor each event runs (hook when not named)
SERVER = "harness"


def read_json(path: str | Path) -> dict[str, Any]:
    """A JSON settings file as an object.

    Args:
        path: the file.

    Returns:
        Its object; {} when the file does not exist.

    Raises:
        ValueError: the file is not JSON, or not a JSON object.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object: fix it by hand first")
    return data


def write_json(path: str | Path, data: dict[str, Any]) -> None:
    """Write a JSON settings file in one atomic rename (its folder is made when missing).

    Args:
        path: the file.
        data: the object written.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def hook_command(python: str, boot: str | Path, entry: str = "hook") -> str:
    """The command of one hook: the anchor run by python with an entry.

    Args:
        python: the Python that runs it.
        boot: the anchor.
        entry: the anchor's entry (hook, session_start).

    Returns:
        '"<python>" "<boot>" <entry>'.
    """
    return f'"{python}" "{boot}" {entry}'


def ours(entry: Any, boot: str | Path) -> bool:
    """Whether a hook entry of the settings runs boot.

    Args:
        entry: one entry of a hook group's hooks, as the settings hold it (any JSON value).
        boot: the anchor (or the legacy boot.py) whose hooks, rules and server are the harness's.

    Returns:
        True when it is an object whose command names boot.
    """
    return isinstance(entry, dict) and str(boot) in str(entry.get("command", ""))


def install_hooks(settings_path: str | Path, python: str, boot: str | Path) -> list[str]:
    """Add the harness's hooks to the user's settings, beside the hooks already there.

    Args:
        settings_path: the user's settings.json.
        python: the Python that runs the hooks.
        boot: the anchor the hooks run.

    Returns:
        The events a hook was added for (an event that runs boot already is left as it is).

    Raises:
        ValueError: the settings are not a JSON object.
    """
    data = read_json(settings_path)
    hooks = data.setdefault("hooks", {})
    added = []
    for event, matcher in EVENTS.items():
        groups = hooks.setdefault(event, [])
        if any(ours(h, boot) for g in groups if isinstance(g, dict) for h in g.get("hooks", [])):
            continue
        group = {"hooks": [{"type": "command", "command": hook_command(python, boot, ENTRY.get(event, "hook"))}]}
        groups.append({"matcher": matcher, **group} if matcher else group)
        added.append(event)
    write_json(settings_path, data)
    return added


def remove_hooks(settings_path: str | Path, boot: str | Path) -> list[str]:
    """Take the hooks that run boot out of the user's settings; a group left empty goes too.

    Args:
        settings_path: the user's settings.json.
        boot: the anchor (or the legacy boot.py) whose hooks, rules and server are the harness's.

    Returns:
        The events whose group was taken out.

    Raises:
        ValueError: the settings are not a JSON object.
    """
    data = read_json(settings_path)
    removed = []
    for event, groups in list(data.get("hooks", {}).items()):
        kept = []
        for g in groups:
            inner = [h for h in g.get("hooks", []) if not ours(h, boot)] if isinstance(g, dict) else None
            if inner is None or inner:
                kept.append({**g, "hooks": inner} if inner is not None else g)
            else:
                removed.append(event)
        data["hooks"][event] = kept
    write_json(settings_path, data)
    return removed


def allow_rules(python: str, boot: str | Path, user_home: Optional[str | Path] = None) -> list[str]:
    """The permission rules that allow the harness's own CLI, in each form a session writes it: the installer's python
    or plain python3, the boot path quoted or not, or from ~ when it is under the user's home.

    Args:
        python: the installer's Python.
        boot: the anchor.
        user_home: the user's home folder, or None to leave out the ~ form.

    Returns:
        Each rule as Bash(<form> cli:*), once.
    """
    paths = list(dict.fromkeys([str(boot), Path(boot).as_posix()]))
    forms = [f'"{python}" "{p}"' for p in paths] + [f'python3 "{p}"' for p in paths] + [f"python3 {p}" for p in paths]
    tilde = tilde_form(boot, user_home)
    if tilde:
        forms.append(f"python3 {tilde}")
    return [f"Bash({f} cli:*)" for f in dict.fromkeys(forms)]


def tilde_form(boot: str | Path, user_home: Optional[str | Path]) -> str:
    """The anchor's path from ~, when it is under the user's home.

    Args:
        boot: the anchor.
        user_home: the user's home folder, or None.

    Returns:
        "~/<path>", or "" when there is no home or boot is not under it.
    """
    try:
        return "~/" + Path(boot).relative_to(Path(user_home).resolve()).as_posix() if user_home else ""
    except ValueError:
        return ""


def our_rule(rule: Any, boot: str | Path, user_home: Optional[str | Path]) -> bool:
    """Whether a permission rule of the settings is one install put in: a rule for boot's CLI.

    Args:
        rule: one entry of the settings' allowed rules (any JSON value).
        boot: the anchor (or the legacy boot.py) whose hooks, rules and server are the harness's.
        user_home: the user's home folder (for the ~ form), or None.

    Returns:
        True when it is a string ending in " cli:*)" that names boot.
    """
    marks = [str(boot), Path(boot).as_posix(), tilde_form(boot, user_home)]
    return isinstance(rule, str) and rule.endswith(" cli:*)") and any(m and m in rule for m in marks)


def install_rules(settings_path: str | Path, rules: list[str]) -> list[str]:
    """Add permission rules to the settings' allowed rules.

    Args:
        settings_path: the user's settings.json.
        rules: the rules to allow (allow_rules).

    Returns:
        The rules added (those not there already).

    Raises:
        ValueError: the settings are not a JSON object.
    """
    data = read_json(settings_path)
    allow = data.setdefault("permissions", {}).setdefault(PERMISSIONS_KEY, [])
    added = [r for r in rules if r not in allow]
    allow.extend(added)
    write_json(settings_path, data)
    return added


def remove_rules(settings_path: str | Path, boot: str | Path, user_home: Optional[str | Path]) -> list[str]:
    """Take the rules that allow boot's CLI out of the settings' allowed rules.

    Args:
        settings_path: the user's settings.json.
        boot: the anchor (or the legacy boot.py) whose hooks, rules and server are the harness's.
        user_home: the user's home folder (for the ~ form), or None.

    Returns:
        The rules taken out; [] when the settings hold no list of allowed rules.

    Raises:
        ValueError: the settings are not a JSON object.
    """
    data = read_json(settings_path)
    allow = data.get("permissions", {}).get(PERMISSIONS_KEY)
    if not isinstance(allow, list):
        return []
    removed = [r for r in allow if our_rule(r, boot, user_home)]
    data["permissions"][PERMISSIONS_KEY] = [r for r in allow if r not in removed]
    write_json(settings_path, data)
    return removed


def server_entry(python: str, boot: str | Path) -> dict[str, Any]:
    """The MCP server entry of the harness: the anchor's mcp_server entry over stdio.

    Args:
        python: the Python that runs it.
        boot: the anchor.

    Returns:
        {type: "stdio", command: python, args: [boot, "mcp_server"]}.
    """
    return {"type": "stdio", "command": str(python), "args": [str(boot), "mcp_server"]}


def install_server(claude_json: str | Path, python: str, boot: str | Path, use_cli: bool = True) -> str:
    """Register the MCP server at user scope: through the claude CLI when there is one, else in ~/.claude.json.

    Args:
        claude_json: the user's ~/.claude.json.
        python: the Python that runs the server.
        boot: the anchor.
        use_cli: whether to try the claude CLI first.

    Returns:
        Where it was registered: "claude mcp add-json --scope user", or the path of claude_json.

    Raises:
        ValueError: claude_json is not a JSON object (when it is written).
    """
    entry = server_entry(python, boot)
    cli = shutil.which("claude") if use_cli else None
    if cli:
        subprocess.run([cli, "mcp", "remove", "--scope", "user", SERVER], capture_output=True)
        p = subprocess.run([cli, "mcp", "add-json", "--scope", "user", SERVER, json.dumps(entry)], capture_output=True,
                           text=True)
        if p.returncode == 0:
            return "claude mcp add-json --scope user"
    data = read_json(claude_json)
    data.setdefault("mcpServers", {})[SERVER] = entry
    write_json(claude_json, data)
    return str(claude_json)


def remove_server(claude_json: str | Path, boot: str | Path, use_cli: bool = True) -> None:
    """Take the harness's MCP server out: through the claude CLI when there is one, and from ~/.claude.json when its
    entry there runs boot.

    Args:
        claude_json: the user's ~/.claude.json.
        boot: the anchor (or the legacy boot.py) whose hooks, rules and server are the harness's.
        use_cli: whether to use the claude CLI too.

    Raises:
        ValueError: claude_json is not a JSON object.
    """
    cli = shutil.which("claude") if use_cli else None
    if cli:
        subprocess.run([cli, "mcp", "remove", "--scope", "user", SERVER], capture_output=True)
    data = read_json(claude_json)
    server = data.get("mcpServers", {}).get(SERVER)
    if server and str(boot) in json.dumps(server):
        del data["mcpServers"][SERVER]
        write_json(claude_json, data)


def legacy(home: str | Path) -> Path:
    """What a machine set up before the anchor names: .claude/entry/boot.py of this home.

    Args:
        home: the home, the .claude folder of this clone.

    Returns:
        The resolved path of its entry/boot.py.
    """
    return (Path(home) / "entry" / "boot.py").resolve()


def install(home: str | Path, user_dir: str | Path, claude_json: str | Path, python: str, use_cli: bool = True) -> str:
    """Install the harness for the user: the legacy wiring out, the hooks, the CLI's rules and the MCP server in.

    Args:
        home: the home, the .claude folder of this clone.
        user_dir: the user's ~/.claude folder (its settings.json).
        claude_json: the user's ~/.claude.json.
        python: the Python that runs the hooks and the server.
        use_cli: whether to register the server through the claude CLI when there is one.

    Returns:
        What was installed, for the user.

    Raises:
        ValueError: the anchor is missing, or a settings file is not a JSON object.
    """
    boot = anchor(home)
    if not boot.is_file():
        raise ValueError(f"{boot} is missing: run install from a clone of the harness")
    remove_hooks(Path(user_dir) / "settings.json", legacy(home))
    remove_rules(Path(user_dir) / "settings.json", legacy(home), Path(user_dir).resolve().parent)
    added = install_hooks(Path(user_dir) / "settings.json", python, boot)
    install_rules(Path(user_dir) / "settings.json", allow_rules(python, boot, Path(user_dir).resolve().parent))
    where = install_server(claude_json, python, boot, use_cli)
    return (f"Hooks of {', '.join(added) or 'every event (already there)'} run {boot}; the MCP server '{SERVER}' is "
            f"registered ({where}); its CLI is allowed. New Claude Code sessions run under the harness from their "
            f"first prompt; its home is {Path(home).resolve()}.")


def uninstall(home: str | Path, user_dir: str | Path, claude_json: str | Path, use_cli: bool = True) -> str:
    """Take out what install put in, for the anchor and for the legacy boot.py.

    Args:
        home: the home, the .claude folder of this clone.
        user_dir: the user's ~/.claude folder (its settings.json).
        claude_json: the user's ~/.claude.json.
        use_cli: whether to remove the server through the claude CLI too.

    Returns:
        What was removed, for the user.

    Raises:
        ValueError: a settings file is not a JSON object.
    """
    boot, removed = anchor(home), []
    for script in (boot, legacy(home)):
        removed += remove_hooks(Path(user_dir) / "settings.json", script)
        remove_rules(Path(user_dir) / "settings.json", script, Path(user_dir).resolve().parent)
        remove_server(claude_json, script, use_cli)
    return (f"Removed the harness's hooks ({', '.join(removed) or 'none were there'}), the rules that allow its CLI "
            f"and its MCP server.")
