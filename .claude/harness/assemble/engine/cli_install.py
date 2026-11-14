"""Install the harness for every Claude Code session of a user (entry/install.py): the hooks go into the user's own
settings (~/.claude/settings.json), merged with the hooks already there, and the harness's MCP server is registered at
user scope (~/.claude.json mcpServers), so any repository a session works on runs under the harness from its first
prompt. The harness's home is the .claude folder of this clone: its ledger, config and releases. Safe to run again;
uninstall takes out only what install put in. Every file is rewritten in one atomic rename."""
import json
import os
import shutil
import subprocess
from pathlib import Path

EVENTS = {"PreToolUse": "*", "PostToolUse": "*", "UserPromptSubmit": None, "Stop": None}
SERVER = "harness"


def read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object: fix it by hand first")
    return data


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def hook_command(python, boot):
    return f'"{python}" "{boot}" hook'


def ours(entry, boot):
    return isinstance(entry, dict) and str(boot) in str(entry.get("command", ""))


def install_hooks(settings_path, python, boot):
    data = read_json(settings_path)
    hooks = data.setdefault("hooks", {})
    added = []
    for event, matcher in EVENTS.items():
        groups = hooks.setdefault(event, [])
        if any(ours(h, boot) for g in groups if isinstance(g, dict) for h in g.get("hooks", [])):
            continue
        group = {"hooks": [{"type": "command", "command": hook_command(python, boot)}]}
        groups.append({"matcher": matcher, **group} if matcher else group)
        added.append(event)
    write_json(settings_path, data)
    return added


def remove_hooks(settings_path, boot):
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


def server_entry(python, boot):
    return {"type": "stdio", "command": str(python), "args": [str(boot), "mcp_server"]}


def install_server(claude_json, python, boot, use_cli=True):
    """Register the MCP server at user scope: through the claude CLI when there is one, else in ~/.claude.json."""
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


def remove_server(claude_json, boot, use_cli=True):
    cli = shutil.which("claude") if use_cli else None
    if cli:
        subprocess.run([cli, "mcp", "remove", "--scope", "user", SERVER], capture_output=True)
    data = read_json(claude_json)
    server = data.get("mcpServers", {}).get(SERVER)
    if server and str(boot) in json.dumps(server):
        del data["mcpServers"][SERVER]
        write_json(claude_json, data)


def install(home, user_dir, claude_json, python, use_cli=True):
    boot = (Path(home) / "entry" / "boot.py").resolve()
    if not boot.is_file():
        raise ValueError(f"{boot} is missing: run install from a clone of the harness")
    added = install_hooks(Path(user_dir) / "settings.json", python, boot)
    where = install_server(claude_json, python, boot, use_cli)
    return (f"Hooks of {', '.join(added) or 'every event (already there)'} run {boot}; the MCP server '{SERVER}' is "
            f"registered ({where}). New Claude Code sessions run under the harness from their first prompt; its home "
            f"is {Path(home).resolve()}.")


def uninstall(home, user_dir, claude_json, use_cli=True):
    boot = (Path(home) / "entry" / "boot.py").resolve()
    removed = remove_hooks(Path(user_dir) / "settings.json", boot)
    remove_server(claude_json, boot, use_cli)
    return f"Removed the harness's hooks ({', '.join(removed) or 'none were there'}) and its MCP server."
