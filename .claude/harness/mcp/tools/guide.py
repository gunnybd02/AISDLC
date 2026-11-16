"""guide: read a skill of the library, or the actions of a block with their arguments (one action with topic)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from harness.mcp.actions.table import ActionTable, signature
from harness.mcp.server.tool import Result, Tool

if TYPE_CHECKING:
    from harness.mcp.skills.library import Skills


class Guide(Tool):
    """The guide tool: a skill's text, or the actions of a block."""
    name = "guide"
    description = "Read a skill (mode skills) or the actions of a block (mode mcp); topic narrows to one action."
    schema = {"type": "object", "properties": {"name": {"type": "string"}, "mode": {"type": "string", "enum": ["skills", "mcp"]},
                                               "topic": {"type": "string"}}, "required": ["name", "mode"]}

    def __init__(self, skills: Skills, table: ActionTable) -> None:
        """Keep the library and the action table it reads.

        Args:
            skills: the library of skills.
            table: the action table.
        """
        self.skills, self.table = skills, table

    def call(self, args: dict[str, Any]) -> Result:
        """Answer {name, mode, topic?}: the whole text of a skill (mode skills), or the block's actions, one line
        each with its signature, summary and effect (mode mcp; topic keeps one action); an error for an unknown
        mode, skill, block or action."""
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
