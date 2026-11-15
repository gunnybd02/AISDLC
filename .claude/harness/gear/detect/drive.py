"""DriveGuard: a Google Drive file a session would take away or move. The ledger copies of every session go to a
Drive folder (the store, utils/ledger/export.py), and a store only grows: trashing a Drive file is drive.remove, moving
or renaming one is drive.move, and the user is asked each time. Uploading, reading and searching are free. The tool is
known by its name (mcp__<a Drive server>__<operation>): the harness cannot see which folder a file id is in, so every
Drive file is guarded alike."""
from harness.utils.contracts import Detector, Finding

REMOVE = ("trash_file", "delete_file")
MOVE_KEYS = ("title", "parentId")


class DriveGuard(Detector):
    def detect(self, event, facts):
        parts = str(event.tool or "").split("__")
        if event.kind != "PreToolUse" or len(parts) < 3 or parts[0] != "mcp" or "drive" not in parts[1].lower():
            return []
        operation, given = parts[-1].lower(), event.input if isinstance(event.input, dict) else {}
        file_id = str(given.get("fileId") or given.get("file_id") or "a file")
        if operation in REMOVE:
            return [Finding("drive.remove", file_id)]
        if operation == "update_file" and any(given.get(k) for k in MOVE_KEYS):
            return [Finding("drive.move", file_id)]
        return []
