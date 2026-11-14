"""Places: the files a call writes, as absolute paths with forward slashes, for the edit gate (detect/tracked.py, detect/planfiles.py).
- An editing tool (Write, Edit, MultiEdit, NotebookEdit) writes its file; a relative path is read from the cwd.
- A shell call (Bash, PowerShell) before it runs is read whole (utils/shell) and each command that really runs is
  looked up in the tables below: a known read writes nothing; a known write names its files (its operands, a
  redirection, the destination of a copy, the file of a download); anything else is unread: a command the tables do
  not know, a target the shell makes when it runs ($F, *.py, ~), code run inline that may write, a git that changes
  the work tree. An unread call gives shell_unread (why), shell_command and shell_said (the agent's own words on
  what it does: the tool's description), so the gate can ask the user.
After cd X, a relative path is read both from the folder before and from X: the gate sees every place it may be.
- mentions: every place a call names, read or written (utils/shell/mentions.py for a shell line; the path of Read,
  Grep, Glob, LS and NotebookRead, their folder when they name none), so the gate keeps the harness's state shut.
- harness_cli: the shell line runs the harness's own CLI (the session is linked to it, as for its MCP tools)."""
from harness.utils.contracts import Translator
from harness.utils.shell.paths import absolute
from harness.utils.shell.mentions import mentioned, runs_harness
from harness.utils.shell.place_ops import shell_places

KEYS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
SHELL_TOOLS = {"Bash": "bash", "PowerShell": "powershell"}
READERS = {"Read": ("file_path",), "NotebookRead": ("notebook_path",), "LS": ("path",), "Grep": ("path",),
           "Glob": ("path", "pattern")}


def reader_places(event):
    """The places a reading tool names: its path (a Glob's pattern under it), or its folder when it names none."""
    keys = READERS[event.tool]
    path = event.input.get(keys[0])
    folder = absolute(path, event.cwd) if isinstance(path, str) and path else absolute(".", event.cwd)
    out = [folder]
    pattern = event.input.get(keys[1]) if len(keys) > 1 else None
    if isinstance(pattern, str) and pattern:
        out.append(absolute(pattern, folder))
    return out


class Places(Translator):
    def translate(self, event):
        dialect = SHELL_TOOLS.get(event.tool)
        if dialect:
            command = event.input.get("command")
            if event.kind != "PreToolUse" or not isinstance(command, str):
                return {}
            said = event.input.get("description")
            facts = shell_places(command, dialect, event.cwd, said if isinstance(said, str) else "")
            seen = mentioned(command, dialect, event.cwd)
            if runs_harness(command, dialect):
                facts = {**facts, "harness_cli": True}
            return {**facts, "mentions": seen} if seen else facts
        if event.tool in READERS:
            return {"mentions": reader_places(event)} if event.kind == "PreToolUse" else {}
        key = KEYS.get(event.tool)
        path = event.input.get(key) if key else None
        return {"writes": [absolute(path, event.cwd)]} if isinstance(path, str) and path else {}
