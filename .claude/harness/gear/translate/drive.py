"""DriveCalls: a Google Drive file a session would take away or move, as a rule action (kind drive, op remove or
move, detail the file id); the when rows drive.remove and drive.move decide it. The ledger copies of every session go to a
Drive folder (the store, utils/ledger/export.py), and a store only grows: trashing a Drive file is drive.remove, moving
or renaming one is drive.move, and the user is asked each time. Uploading, reading and searching are free.

A Drive call is known by what it is, not by its server's name: Claude Code names a connector's tools by its name
(mcp__Google_Drive__trash_file) or by an id (mcp__caaed075-...__trash_file). So it is an MCP tool whose server's name
holds "drive", or whose call names a Drive file (fileId). The harness cannot see which folder a file id is in, so every
Drive file is guarded alike."""
from __future__ import annotations

from typing import Any

from harness.utils.contracts import RULE_ACTIONS, Event, Translator
from harness.utils.shapes import Facts

REMOVE = ("trash_file", "delete_file")
FILE_KEYS = ("fileId", "file_id")
MOVE_KEYS = ("title", "name", "parentId", "parent_id")


class DriveCalls(Translator):
    """The rule action of a Drive call that takes a file away (op remove) or moves or renames it (op move)."""
    VOCABULARY = ("kind", "op")

    def translate(self, event: Event) -> Facts:
        """One rule action for a Drive file trashed or deleted, or moved or renamed, before the call runs; else {}."""
        parts = str(event.tool or "").split("__")
        given: dict[str, Any] = event.input if isinstance(event.input, dict) else {}
        if event.kind != "PreToolUse" or len(parts) < 3 or parts[0] != "mcp":
            return {}
        file_id = next((str(given[k]) for k in FILE_KEYS if given.get(k)), "")
        if "drive" not in parts[1].lower() and not file_id:
            return {}
        operation = parts[-1].lower()
        op = "remove" if operation in REMOVE else \
            "move" if operation == "update_file" and any(given.get(k) for k in MOVE_KEYS) else ""
        return {RULE_ACTIONS: [{"kind": "drive", "op": op, "detail": file_id or "a file"}]} if op else {}
