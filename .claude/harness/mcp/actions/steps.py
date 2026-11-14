"""steps: the end of a plan. step_done is the only way its change is committed: the harness checks it, then commits."""
from harness.utils.contracts import WRITE, McpAction
from harness.utils.plan.steps import step_done

ACTIONS = [("steps.step_done", "StepDone")]


class StepDone(McpAction):
    block, name, effect = "steps", "step_done", WRITE
    summary = ("Commit the plan's changed files with this message, after a passing verify; the plan is then delivered. "
               "Refused with why: no passing verify, a file changed since, a secret, or nothing changed")
    args_schema = {"type": "object", "properties": {"plan": {"type": "string"}, "message": {"type": "string"}},
                   "required": ["plan", "message"]}
    needs = ("plans",)

    def run(self, ctx, args):
        return step_done(ctx.ports["plans"], args["plan"], args["message"])
