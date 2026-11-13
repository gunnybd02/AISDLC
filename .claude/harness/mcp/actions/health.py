"""health: the health of the harness, what the blocks declare and every problem of the tree."""
from harness.mcp.actions.table import McpAction

BLOCK = "health"
ABOUT = "The health of the harness: what the blocks declare"


class Items(McpAction):
    name = "items"
    about = "The items of the blocks, one per line: block, kind, name"
    needs = ("items",)

    def __call__(self):
        return "\n".join(f"{i.block} {i.kind} {i.name}" for i in self.ports["items"].values())


class Doctor(McpAction):
    name = "doctor"
    about = "Every problem of the tree: the indexes, the build, the skills, the nets"
    needs = ("doctor",)

    def __call__(self):
        return self.ports["doctor"]()


ACTIONS = [Items, Doctor]
