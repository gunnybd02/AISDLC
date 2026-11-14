"""plan steps: step_done commits the current step of the session's plan (the harness checks it, then commits; the last
step delivers the plan), step_skip gives the current step up. git commit from the shell is refused."""
from harness.utils.contracts import READ, WRITE, ActionError, McpAction
from harness.utils.plan.closing import close_question
from harness.utils.plan.steps import step_done, step_skip

ACTIONS = [("plan.step_done", "StepDone"), ("plan.step_skip", "StepSkip"), ("plan.plan_close", "PlanClose")]
NO_SESSION = "no session: the harness has not seen this session's prompt yet"


def session_of(ctx):
    sid = ctx.ports["session"]()
    if not sid:
        raise ActionError(NO_SESSION)
    return sid


class StepDone(McpAction):
    block, name, effect = "plan", "step_done", WRITE
    summary = ("End the current step: the harness checks what it owes (its behaviours' tests, a green verify of the "
               "current files, no secret, not a protected branch) and commits the step's files with this message")
    args_schema = {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}
    needs = ("plans", "session")

    def run(self, ctx, args):
        return step_done(ctx.ports["plans"], session_of(ctx), args["message"])


class StepSkip(McpAction):
    block, name, effect = "plan", "step_skip", WRITE
    summary = "Give the current step up with a reason (one line); its behaviours are kept as skipped"
    args_schema = {"type": "object", "properties": {"why": {"type": "string"}}, "required": ["why"]}
    needs = ("plans", "session")

    def run(self, ctx, args):
        return step_skip(ctx.ports["plans"], session_of(ctx), args["why"])


class PlanClose(McpAction):
    block, name, effect = "plan", "plan_close", READ  # it only gives the question; the user's answer closes
    summary = ("Close the session's plan: the harness builds the account from the ledger (commits, files vs plan, "
               "verify, skipped) and gives the form; the user closes it (delivered, abandoned) or keeps it open")
    args_schema = {"type": "object", "properties": {"summary": {"type": "string"}, "exceptions": {"type": "array"}},
                   "required": []}
    needs = ("plans", "session")

    def run(self, ctx, args):
        return close_question(ctx.ports["plans"], session_of(ctx), args.get("summary"), args.get("exceptions"))
