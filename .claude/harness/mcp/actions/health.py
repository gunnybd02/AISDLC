"""health: the health of the harness, what the blocks declare and every problem of the tree."""
from harness.utils.contracts import READ, McpAction

ACTIONS = [("health.items", "Items"), ("health.doctor", "Doctor")]


class Items(McpAction):
    block, name, effect = "health", "items", READ
    summary = "The health of the harness: the items of the blocks, one per line (block, kind, name)"
    needs = ("items",)

    def run(self, ctx, args):
        return "\n".join(f"{i.block} {i.kind} {i.name}" for i in ctx.ports["items"].values())


class Doctor(McpAction):
    block, name, effect = "health", "doctor", READ
    summary = "Every problem of the tree: the indexes, the build, the skills, the nets"
    needs = ("doctor",)

    def run(self, ctx, args):
        return ctx.ports["doctor"]()
