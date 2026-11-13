"""steps: the end of a plan. step_done is the only way its change is committed: the harness checks it, then commits."""
from harness.mcp.actions.table import McpAction
from harness.utils.plan.steps import step_done

BLOCK = "steps"
ABOUT = "Commit the verified change of a plan: the harness checks it and makes the commit; git commit is refused"


class StepDone(McpAction):
    name = "step_done"
    about = ("Commit the plan's changed files with this message, after a passing verify; the plan is then delivered. "
             "Refused with why: no passing verify, a file changed since, a secret, or nothing changed")
    args = {"plan": "string", "message": "string"}
    needs = ("plans",)

    def __call__(self, plan, message):
        return step_done(self.ports["plans"], plan, message)


ACTIONS = [StepDone]
