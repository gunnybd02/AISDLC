"""health: the health of the harness, what the blocks declare and every problem of the tree."""
from __future__ import annotations

from typing import Any

from harness.utils.contracts import READ, ActionContext, McpAction

ACTIONS = [("health.items", "Items"), ("health.doctor", "Doctor")]


class Items(McpAction):
    """health.items: the items the blocks declare."""
    block, name, effect = "health", "items", READ
    summary = "The health of the harness: the items of the blocks, one per line (block, kind, name)"
    needs = ("items",)

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Answer the items of the blocks, one per line: "<block> <kind> <name>"."""
        return "\n".join(f"{i.block} {i.kind} {i.name}" for i in ctx.ports["items"].values())


class Doctor(McpAction):
    """health.doctor: every problem of the tree."""
    block, name, effect = "health", "doctor", READ
    summary = "Every problem of the tree: the indexes, the build, the skills, the nets"
    needs = ("doctor",)

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Answer every problem of the tree, as the doctor port gives it."""
        return ctx.ports["doctor"]()
