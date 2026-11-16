"""find: what fits the work - the skills of the library and the blocks of the action table, ranked by how many words
of the request their name and description hold."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from harness.mcp.server.tool import Result, Tool

if TYPE_CHECKING:
    from harness.mcp.actions.table import ActionTable
    from harness.mcp.skills.library import Skills

MODES = ("skills", "mcp")


def words(text: object) -> set[str]:
    """The words of a text, lower case (runs of ASCII letters and digits).

    Args:
        text: any value; it is read as its str().

    Returns:
        The set of its words.
    """
    return set(re.findall(r"[a-z0-9]+", str(text).lower()))


class Find(Tool):
    """The find tool: skills and blocks ranked by the words of the request."""
    name = "find"
    description = "What fits the work: skills and tool blocks ranked by the words of the request. mode narrows it."
    schema = {"type": "object", "properties": {"query": {"type": "string"}, "mode": {"type": "string", "enum": list(MODES)}},
              "required": ["query"]}

    def __init__(self, skills: Skills, table: ActionTable) -> None:
        """Keep the library and the action table it ranks.

        Args:
            skills: the library of skills.
            table: the action table, whose blocks it ranks.
        """
        self.skills, self.table = skills, table

    def call(self, args: dict[str, Any]) -> Result:
        """Rank the skills and blocks by the words of query ({query, mode?}): one line "[kind] name - description
        (score n)" each that holds a word, best first, then how to go on; an error for an unknown mode."""
        query, mode = words(args.get("query", "")), args.get("mode")
        if mode is not None and mode not in MODES:
            return Result(f"mode is one of {', '.join(MODES)}", True)
        found = []
        if mode in (None, "skills"):
            found += [("skills", s.name, s.description) for s in self.skills.all()]
        if mode in (None, "mcp"):
            found += [("mcp", b, self.table.about(b)) for b in self.table.blocks]
        scored = sorted(((len(query & words(f"{n} {d}")), k, n, d) for k, n, d in found), key=lambda x: (-x[0], x[2]))
        lines = [f"[{k}] {n} - {d} (score {s})" for s, k, n, d in scored if s]
        if not lines:
            return Result("Nothing fits these words; try others, or guide(name, mode) for a name you know.")
        return Result("\n".join(lines + ["Next: guide(name, mode) to learn how to use one."]))
