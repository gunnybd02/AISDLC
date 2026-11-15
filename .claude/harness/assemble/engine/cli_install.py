"""Install the harness for every Claude Code session of a user (harness/entry/install.py): the hooks go into the
user's own settings (~/.claude/settings.json), merged with the hooks already there (SessionStart brings the harness up to date
when a session begins: harness/entry/session_start.py), and the harness's MCP server is registered at
user scope (~/.claude.json mcpServers), so any repository a session works on runs under the harness from its first
prompt. Its own CLI (anchor.py cli ...) is allowed in the user's permissions, so a session in auto mode may run it:
the hooks still judge every call, and a new release still needs the user's word. The harness's home is the .claude
folder of this clone: its ledger, config and releases. Safe to run again; uninstall takes out only what install put in.
Every file is rewritten in one atomic rename. What a machine set up before the anchor holds (hooks, rules and
server naming .claude/entry/boot.py) is taken out first, so nothing runs twice."""
import json
import os
import shutil
import subprocess
from pathlib import Path

from harness.utils.contracts import PERMISSIONS_KEY
from harness.utils.gateway.release import anchor

EVENTS = {"PreToolUse": "*", "PostToolUse": "*", "UserPromptSubmit": None, "Stop": None, "SessionStart": None}
ENTRY = {"SessionStart": "session_start"}  # the entry of the anchor each event runs (hook when not named)
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


def hook_command(python, boot, entry="hook"):
    return f'"{python}" "{boot}" {entry}'


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
        group = {"hooks": [{"type": "command", "command": hook_command(python, boot, ENTRY.get(event, "hook"))}]}
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


def allow_rules(python, boot, user_home=None):
    """The permission rules that allow the harness's own CLI, in each form a session writes it: the installer's python
    or plain python3, the boot path quoted or not, or from ~ when it is under the user's home."""
    paths = list(dict.fromkeys([str(boot), Path(boot).as_posix()]))
    forms = [f'"{python}" "{p}"' for p in paths] + [f'python3 "{p}"' for p in paths] + [f"python3 {p}" for p in paths]
    tilde = tilde_form(boot, user_home)
    if tilde:
        forms.append(f"python3 {tilde}")
    return [f"Bash({f} cli:*)" for f in dict.fromkeys(forms)]


def tilde_form(boot, user_home):
    try:
        return "~/" + Path(boot).relative_to(Path(user_home).resolve()).as_posix() if user_home else ""
    except ValueError:
        return ""


def our_rule(rule, boot, user_home):
    marks = [str(boot), Path(boot).as_posix(), tilde_form(boot, user_home)]
    return isinstance(rule, str) and rule.endswith(" cli:*)") and any(m and m in rule for m in marks)


def install_rules(settings_path, rules):
    data = read_json(settings_path)
    allow = data.setdefault("permissions", {}).setdefault(PERMISSIONS_KEY, [])
    added = [r for r in rules if r not in allow]
    allow.extend(added)
    write_json(settings_path, data)
    return added


def remove_rules(settings_path, boot, user_home):
    data = read_json(settings_path)
    allow = data.get("permissions", {}).get(PERMISSIONS_KEY)
    if not isinstance(allow, list):
        return []
    removed = [r for r in allow if our_rule(r, boot, user_home)]
    data["permissions"][PERMISSIONS_KEY] = [r for r in allow if r not in removed]
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


def legacy(home):
    """What a machine set up before the anchor names: .claude/entry/boot.py of this home."""
    return (Path(home) / "entry" / "boot.py").resolve()


def install(home, user_dir, claude_json, python, use_cli=True):
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


def uninstall(home, user_dir, claude_json, use_cli=True):
    boot, removed = anchor(home), []
    for script in (boot, legacy(home)):
        removed += remove_hooks(Path(user_dir) / "settings.json", script)
        remove_rules(Path(user_dir) / "settings.json", script, Path(user_dir).resolve().parent)
        remove_server(claude_json, script, use_cli)
    return (f"Removed the harness's hooks ({', '.join(removed) or 'none were there'}), the rules that allow its CLI "
            f"and its MCP server.")
