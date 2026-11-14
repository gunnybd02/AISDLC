"""gitlab: the merge request of a pushed plan branch, opened through GitLab REST after the user confirms its full text in
a form (one Yes, one merge request); the text holds no AI mark and no banned word."""
from harness.utils.contracts import WRITE, ActionError, McpAction
from harness.utils.plan.ship import mr_open

ACTIONS = [("git.mr_open", "MrOpen")]


class MrOpen(McpAction):
    block, name, effect = "git", "mr_open", WRITE
    summary = ("Open a merge request of the pushed branch into target (default main): the user confirms the full text "
               "first; no AI mark or banned word in it")
    args_schema = {"type": "object", "properties": {"title": {"type": "string"}, "description": {"type": "string"},
                                                    "target": {"type": "string"}}, "required": ["title", "description"]}
    needs = ("plans", "session", "banned")

    def run(self, ctx, args):
        sid = ctx.ports["session"]()
        if not sid:
            raise ActionError("no session: the harness has not seen this session's prompt yet")
        return mr_open(ctx.ports["plans"], sid, args["title"], args["description"], args.get("target") or "main",
                       ctx.ports["banned"]())
