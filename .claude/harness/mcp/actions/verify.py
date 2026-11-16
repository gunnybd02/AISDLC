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
        """Run the plan's verify command (its unit's, else the config's: utils/plan/verify.verify) and keep the
        receipt; answer the result. ActionError when there is no such plan or no command."""
        try:
            return verify(ctx.ports["plans"], ctx.ports["verify_command"](), args["plan"])
        except ValueError as e:
            raise ActionError(str(e)) from e
