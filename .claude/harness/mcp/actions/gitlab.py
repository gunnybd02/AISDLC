"""gitlab: the merge request of a pushed plan branch, opened through GitLab REST after the user confirms its full text in
a form (one Yes, one merge request); the text holds no AI mark and no banned word."""
from __future__ import annotations

from typing import Any

from harness.mcp.actions.ledger import store_note
from harness.utils.contracts import WRITE, ActionContext, ActionError, McpAction
from harness.utils.plan.ship import mr_open

ACTIONS = [("git.mr_open", "MrOpen")]


class MrOpen(McpAction):
    """git.mr_open: the merge request of a pushed plan branch, through GitLab REST."""
    block, name, effect = "git", "mr_open", WRITE
    summary = ("Open a merge request of the pushed branch into target (default main): the user confirms the full text "
               "first; no AI mark or banned word in it")
    args_schema = {"type": "object", "properties": {"title": {"type": "string"}, "description": {"type": "string"},
                                                    "target": {"type": "string"}}, "required": ["title", "description"]}
    needs = ("plans", "session", "banned", "store")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Open the merge request of the session's pushed branch once the user confirmed its text
        (utils/plan/ship.mr_open); answer its text (the form question, or the merge request with the store's note).
        ActionError when there is no session."""
        sid = ctx.ports["session"]()
        if not sid:
            raise ActionError("no session: the harness has not seen this session's prompt yet")
        text = mr_open(ctx.ports["plans"], sid, args["title"], args["description"], args.get("target") or "main",
                       ctx.ports["banned"]())
        return text + (store_note(ctx) if text.startswith("Merge request") else "")
