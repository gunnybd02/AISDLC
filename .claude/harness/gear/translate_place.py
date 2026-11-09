"""Places: the files an editing tool writes (Write, Edit, MultiEdit, NotebookEdit), as absolute paths with forward
slashes; a relative path is read from the session's cwd. The gates resolve them further (detect_plan.key). Writes
through the shell come with the shell reader."""
import os

from harness.utils.contracts import Translator

KEYS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}


def absolute(path, cwd):
    return os.path.normpath(os.path.join(cwd or os.getcwd(), path)).replace("\\", "/")


class Places(Translator):
    def translate(self, event):
        key = KEYS.get(event.tool)
        path = event.input.get(key) if key else None
        return {"writes": [absolute(path, event.cwd)]} if isinstance(path, str) and path else {}
