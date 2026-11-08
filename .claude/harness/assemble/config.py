"""Config: the one reader of .claude/project.json, the values of the user (config_net)."""
import json
from dataclasses import dataclass
from pathlib import Path

FILE = "project.json"
FIELDS = ("name", "recipe")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    name: str
    recipe: str

    @classmethod
    def load(cls, claude_dir):
        path = Path(claude_dir) / FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ConfigError(f"{FILE} cannot be read: {e}") from e
        if not isinstance(data, dict) or sorted(data) != sorted(FIELDS) or not all(isinstance(v, str) for v in data.values()):
            raise ConfigError(f"{FILE} holds exactly {', '.join(FIELDS)}, each a string")
        return cls(**data)
