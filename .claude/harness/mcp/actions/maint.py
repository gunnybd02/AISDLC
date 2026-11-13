"""harness: the guards themselves. pause gives the form question that, answered by the user's approval word, pauses the
guards (entry/hook.py holds the pause itself, so it works when the harness is broken); pause_status reads
state/pause.json. The maint grant replaces both (docs/migration-map.md, decision 2)."""
import json
import time
from pathlib import Path

from harness.mcp.actions.table import McpAction
from harness.utils.contracts import YES

BLOCK = "harness"
ABOUT = "The guards themselves: pause them for a while, only through the user's form"
MAX_PAUSE = 120


class Pause(McpAction):
    name = "pause"
    about = "The form question that pauses the guards for N minutes (1 to 120)"
    args = {"minutes": "number", "why": "string"}

    def __call__(self, minutes, why):
        if not isinstance(minutes, int) or not 1 <= minutes <= MAX_PAUSE:
            raise ValueError(f"minutes is a whole number from 1 to {MAX_PAUSE}")
        why = " ".join(str(why).split()).rstrip("?")
        if not why:
            raise ValueError("say why the guards should pause")
        q = f"T\u1eaft guard {minutes} ph\u00fat: {why}?"
        return (f"Ask the user now with AskUserQuestion, one question, exactly: {q} Options: \"{YES}\", "
                f"\"Kh\u00f4ng\". Never fill in the answer. Only the user's {YES} pauses the guards; every call is "
                f"traced while they are paused.")


class PauseStatus(McpAction):
    name = "pause_status"
    about = "Whether the guards are paused, and for how long"
    needs = ("state_dir",)

    def __call__(self):
        try:
            pause = json.loads((Path(self.ports["state_dir"]) / "pause.json").read_text(encoding="utf-8"))
            left = int(float(pause["until"]) - time.time())
        except (OSError, ValueError, KeyError, TypeError):
            return "The guards are on."
        if left <= 0:
            return "The guards are on."
        return f"The guards are paused for {left // 60} more minutes: {pause.get('why')}."


ACTIONS = [Pause, PauseStatus]
