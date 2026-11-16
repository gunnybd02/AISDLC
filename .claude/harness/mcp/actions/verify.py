"""verify: run the unit's tests for an approved plan; a commit needs a passing verify."""
from __future__ import annotations

from typing import Any

from harness.utils.contracts import WRITE, ActionContext, ActionError, McpAction
from harness.utils.plan.verify import verify

ACTIONS = [("verify.run", "Run")]


class Run(McpAction):
    """verify.run: the unit's tests for an approved plan, with a receipt kept."""
    block, name, effect = "verify", "run", WRITE
    summary = "Run the test command in the plan's root and keep the receipt; a commit needs a passing verify"
    args_schema = {"type": "object", "properties": {"plan": {"type": "string"}}, "required": ["plan"]}
    needs = ("plans", "verify_command")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Run the config's verify command for the plan (utils/plan/verify.verify) and keep the receipt; answer
        the result. ActionError when the config names no verify command."""
        command = ctx.ports["verify_command"]()
        if not command:
            raise ActionError("the config names no verify command")
        return verify(ctx.ports["plans"], command, args["plan"])
