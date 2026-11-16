"""Tool: one tool of the MCP server; Result: what it answers, text or an error the model reads."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Result:
    """What a tool answers: the text the model reads, and whether it is an error."""
    text: str
    is_error: bool = False


class Tool(ABC):
    """One tool of the MCP server: its name, its description and the JSON schema of its arguments."""
    name = ""
    description = ""
    schema = {"type": "object", "properties": {}}

    @abstractmethod
    def call(self, args: dict[str, Any]) -> Result:
        """Answer one call of the tool.

        Args:
            args: the call's arguments (an object; the server does not check them against schema).

        Returns:
            The text for the model, or an error result it reads.
        """
        ...

    def listing(self) -> dict[str, Any]:
        """The tool as tools/list shows it.

        Returns:
            {"name", "description", "inputSchema"}.
        """
        return {"name": self.name, "description": self.description, "inputSchema": self.schema}
