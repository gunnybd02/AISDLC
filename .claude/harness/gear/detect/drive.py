"""DriveGuard: a Google Drive file a session would take away or move. The ledger copies of every session go to a
Drive folder (the store, utils/ledger/export.py), and a store only grows: trashing a Drive file is drive.remove, moving
or renaming one is drive.move, and the user is asked each time. Uploading, reading and searching are free.

A Drive call is known by what it is, not by its server's name: Claude Code names a connector's tools by its name
(mcp__Google_Drive__trash_file) or by an id (mcp__caaed075-...__trash_file). So it is an MCP tool whose server's name
holds "drive", or whose call names a Drive file (fileId). The harness cannot see which folder a file id is in, so every
Drive file is guarded alike."""
from harness.utils.contracts import Detector, Finding

REMOVE = ("trash_file", "delete_file")
FILE_KEYS = ("fileId", "file_id")
MOVE_KEYS = ("title", "name", "parentId", "parent_id")


class DriveGuard(Detector):
    def detect(self, event, facts):
        parts = str(event.tool or "").split("__")
        given = event.input if isinstance(event.input, dict) else {}
        if event.kind != "PreToolUse" or len(parts) < 3 or parts[0] != "mcp":
            return []
        file_id = next((str(given[k]) for k in FILE_KEYS if given.get(k)), "")
        if "drive" not in parts[1].lower() and not file_id:
            return []
        operation = parts[-1].lower()
        if operation in REMOVE:
            return [Finding("drive.remove", file_id or "a file")]
        if operation == "update_file" and any(given.get(k) for k in MOVE_KEYS):
            return [Finding("drive.move", file_id or "a file")]
        return []
