"""Config: the one reader of .claude/project.json, the values of the user (config_net).
  name     the project's name
  recipe   the recipe the hook runs
  verify   (optional) the test command of the unit, a list of words run in the plan's root; "{python}" is this Python"""
import json
import sys
from dataclasses import dataclass
from pathlib import Path

FILE = "project.json"
REQUIRED = ("name", "recipe")
OPTIONAL = ("verify",)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    name: str
    recipe: str
    verify: tuple = ()

    @classmethod
    def load(cls, claude_dir):
        path = Path(claude_dir) / FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            raise ConfigError(f"{FILE} cannot be read: {e}") from e
        if not isinstance(data, dict) or set(REQUIRED) - set(data) or set(data) - set(REQUIRED + OPTIONAL) \
                or not all(isinstance(data[k], str) for k in REQUIRED):
            raise ConfigError(f"{FILE} holds {', '.join(REQUIRED)} (strings) and may hold {', '.join(OPTIONAL)}")
        verify = data.get("verify", [])
        if "verify" in data and (not isinstance(verify, list) or not verify or not all(isinstance(w, str) for w in verify)):
            raise ConfigError(f"{FILE}: verify is a list of words, the test command")
        return cls(data["name"], data["recipe"], tuple(sys.executable if w == "{python}" else w for w in verify))
