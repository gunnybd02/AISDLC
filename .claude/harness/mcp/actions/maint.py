"""maint: the maint grant, the user's own switch that turns every guard off for a while (utils/maint/grant.py)."""
import time

from harness.mcp.actions.table import McpAction
from harness.utils.maint.grant import active, question

BLOCK = "maint"
ABOUT = "Turn the guards off for a while: only the user, in the form, grants it"


class Grant(McpAction):
    name = "grant"
    about = "The form question that asks the user to turn the guards off for N minutes (1 to 120)"
    args = {"minutes": "number", "why": "string"}

    def __call__(self, minutes, why):
        return question(minutes, why)


class Status(McpAction):
    name = "status"
    about = "Whether the guards are off, and for how long"
    needs = ("ledger",)

    def __call__(self):
        grant = active(self.ports["ledger"].rows)
        if grant is None:
            return "The guards are on."
        return f"The guards are off for {int(grant['until'] - time.time()) // 60} more minutes: {grant['why']}."


ACTIONS = [Grant, Status]
