"""Places: the files a call writes, as absolute paths with forward slashes, for the edit gate (detect_plan).
- An editing tool (Write, Edit, MultiEdit, NotebookEdit) writes its file; a relative path is read from the cwd.
- A shell call (Bash, PowerShell) before it runs is read whole (utils/shell) and each command that really runs is
  looked up in the tables below: a known read writes nothing; a known write names its files (its operands, a
  redirection, the destination of a copy, the file of a download); anything else is unread: a command the tables do
  not know, a target the shell makes when it runs ($F, *.py, ~), code run inline that may write, a git that changes
  the work tree. An unread call gives shell_unread (why), shell_command and shell_said (the agent's own words on
  what it does: the tool's description), so the gate can ask the user.
After cd X, a relative path is read both from the folder before and from X: the gate sees every place it may be."""
from harness.utils.contracts import Translator
from harness.utils.shell.paths import absolute
from harness.utils.shell.place_ops import shell_places

KEYS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
SHELL_TOOLS = {"Bash": "bash", "PowerShell": "powershell"}


class Places(Translator):
    def translate(self, event):
        dialect = SHELL_TOOLS.get(event.tool)
        if dialect:
            command = event.input.get("command")
            if event.kind != "PreToolUse" or not isinstance(command, str):
                return {}
            said = event.input.get("description")
            return shell_places(command, dialect, event.cwd, said if isinstance(said, str) else "")
        key = KEYS.get(event.tool)
        path = event.input.get(key) if key else None
        return {"writes": [absolute(path, event.cwd)]} if isinstance(path, str) and path else {}
