"""guide: read a skill of the library, or the actions of a block with their arguments (one action with topic)."""
from harness.mcp.actions.table import signature
from harness.mcp.server.tool import Result, Tool


class Guide(Tool):
    name = "guide"
    description = "Read a skill (mode skills) or the actions of a block (mode mcp); topic narrows to one action."
    schema = {"type": "object", "properties": {"name": {"type": "string"}, "mode": {"type": "string", "enum": ["skills", "mcp"]},
                                               "topic": {"type": "string"}}, "required": ["name", "mode"]}

    def __init__(self, skills, table):
        self.skills, self.table = skills, table

    def call(self, args):
        name, mode, topic = args.get("name"), args.get("mode"), args.get("topic")
        if mode == "skills":
            skill = self.skills.get(name)
            return Result(skill.text) if skill else Result(f"No skill {name}; find(words) lists them.", True)
        if mode != "mcp":
            return Result("mode is skills or mcp", True)
        if name not in self.table.blocks:
            return Result(f"No block {name}; find(words, mode='mcp') lists them.", True)
        actions = self.table.actions(name)
        if topic:
            actions = [a for a in actions if a.name == topic]
            if not actions:
                return Result(f"Block {name} has no action {topic}.", True)
        lines = [f"Block {name}: actions (call run(block, action, args)):"]
        return Result("\n".join(lines + [f"  {signature(a)} - {a.summary} [{a.effect}]" for a in actions]))
