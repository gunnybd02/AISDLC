"""Tool: one tool of the MCP server; Result: what it answers, text or an error the model reads."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Result:
    text: str
    is_error: bool = False


class Tool(ABC):
    name = ""
    description = ""
    schema = {"type": "object", "properties": {}}

    @abstractmethod
    def call(self, args) -> Result:
        ...

    def listing(self):
        return {"name": self.name, "description": self.description, "inputSchema": self.schema}
