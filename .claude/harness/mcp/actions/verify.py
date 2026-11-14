"""verify: run the unit's tests for an approved plan; a commit needs a passing verify."""
from harness.utils.contracts import WRITE, ActionError, McpAction
from harness.utils.plan.verify import verify

ACTIONS = [("verify.run", "Run")]


class Run(McpAction):
    block, name, effect = "verify", "run", WRITE
    summary = "Run the test command in the plan's root and keep the receipt; a commit needs a passing verify"
    args_schema = {"type": "object", "properties": {"plan": {"type": "string"}}, "required": ["plan"]}
    needs = ("plans", "verify_command")

    def run(self, ctx, args):
        command = ctx.ports["verify_command"]()
        if not command:
            raise ActionError("the config names no verify command")
        return verify(ctx.ports["plans"], command, args["plan"])
