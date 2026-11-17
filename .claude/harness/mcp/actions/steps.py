"""plan steps: step_done commits the current step of the session's plan (the harness checks it, then commits; the last
step delivers the plan), step_skip gives the current step up. git commit from the shell is refused."""
from __future__ import annotations

from typing import Any

from harness.utils.contracts import ActionContext, ActionError, McpAction, READ, WRITE, session_of
from harness.utils.orchestra import child
from harness.utils.plan.closing import close_question
from harness.utils.plan.steps import step_done, step_skip

ACTIONS = [("plan.step_done", "StepDone"), ("plan.step_skip", "StepSkip"), ("plan.plan_close", "PlanClose")]
class StepDone(McpAction):
    """plan.step_done: the harness checks the current step and commits it."""
    block, name, effect = "plan", "step_done", WRITE
    summary = ("End the current step: the harness checks what it owes (its behaviours' tests, a green verify of the "
               "current files, no secret, not a protected branch) and commits the step's files with this message")
    args_schema = {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}
    needs = ("plans", "session", "commit_judge")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """End the current step of the session's plan (utils/plan/steps.step_done): the harness checks and commits
        it; answer what was done and what comes next."""
        return step_done(ctx.ports["plans"], session_of(ctx), args["message"], ctx.ports["commit_judge"])


class StepSkip(McpAction):
    """plan.step_skip: the current step given up, its behaviours kept as skipped."""
    block, name, effect = "plan", "step_skip", WRITE
    summary = "Give the current step up with a reason (one line); its behaviours are kept as skipped"
    args_schema = {"type": "object", "properties": {"why": {"type": "string"}}, "required": ["why"]}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Give the current step up with why (utils/plan/steps.step_skip); answer the step that follows."""
        return step_skip(ctx.ports["plans"], session_of(ctx), args["why"])


class PlanClose(McpAction):
    """plan.plan_close: the close form of the session's plan."""
    block, name, effect = "plan", "plan_close", READ  # it only gives the question; the user's answer closes
    summary = ("Close the session's plan: the harness builds the account from the ledger (commits, files vs plan, "
               "verify, skipped) and gives the form; the user closes it (delivered, abandoned) or keeps it open")
    args_schema = {"type": "object", "properties": {"summary": {"type": "string"}, "exceptions": {"type": "array"}},
                   "required": []}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Answer the close form of the session's plan with the facts of the ledger (utils/plan/closing). ActionError
        in a child session: nobody could answer the form."""
        sid = session_of(ctx)
        refused = child.refusal(ctx.ports["plans"].ticket(sid), "never closes its plan")
        if refused:
            raise ActionError(refused)
        return close_question(ctx.ports["plans"], sid, args.get("summary"), args.get("exceptions"))
