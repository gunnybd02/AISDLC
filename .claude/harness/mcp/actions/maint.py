"""maint: the maint grant, the user's own switch that turns every guard off for a while (utils/maint/grant.py)."""
from __future__ import annotations

import time
from typing import Any

from harness.utils.contracts import READ, ActionContext, McpAction
from harness.utils.maint.grant import active, question

ACTIONS = [("maint.grant", "Grant"), ("maint.status", "Status")]


class Grant(McpAction):
    """maint.grant: the form question of the maint grant."""
    block, name, effect = "maint", "grant", READ  # it only gives the question; the user's answer grants
    summary = "Turn the guards off for a while: the form question that asks the user for N minutes (1 to 120)"
    args_schema = {"type": "object", "properties": {"minutes": {"type": "integer"}, "why": {"type": "string"}},
                   "required": ["minutes", "why"]}

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Answer the form question that asks the user to turn the guards off for minutes, with why."""
        return question(args["minutes"], args["why"])


class Status(McpAction):
    """maint.status: whether the maint grant is in force."""
    block, name, effect = "maint", "status", READ
    summary = "Whether the guards are off, and for how long"
    needs = ("ledger",)

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Answer whether the guards are on, or for how many more minutes they are off and why."""
        grant = active(ctx.ports["ledger"].rows)
        if grant is None:
            return "The guards are on."
        return f"The guards are off for {int(grant['until'] - time.time()) // 60} more minutes: {grant['why']}."
