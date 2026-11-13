"""verify: run the unit's tests for an approved plan; a commit needs a passing verify."""
from harness.mcp.actions.table import McpAction
from harness.utils.plan.verify import verify

BLOCK = "verify"
ABOUT = "Run the unit's tests for an approved plan; a commit needs a passing verify"


class Run(McpAction):
    name = "run"
    about = "Run the test command in the plan's root and keep the receipt"
    args = {"plan": "string"}
    needs = ("plans", "verify_command")

    def __call__(self, plan):
        command = self.ports["verify_command"]()
        if not command:
            raise ValueError("the config names no verify command")
        return verify(self.ports["plans"], command, plan)


ACTIONS = [Run]
