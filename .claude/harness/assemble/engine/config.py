"""Config: the one reader of .claude/project.json, the values of the user (config_net).
  name     the project's name
  verify   (optional) the test command of the unit, a list of words run in the plan's root; "{python}" is this Python
  ledger   (optional) the absolute path of the real ledger, whose schema the doctor compares read only"""
import json
import sys
from dataclasses import dataclass
from pathlib import Path

FILE = "project.json"
REQUIRED = ("name",)
GONE = {"recipe": "the pipeline is picked by the state of the session (assemble/engine/select.py)"}
OPTIONAL = ("verify", "ledger")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    name: str
    verify: tuple = ()
    ledger: str = ""

    @classmethod
    def load(cls, claude_dir):
        path = Path(claude_dir) / FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            raise ConfigError(f"{FILE} cannot be read: {e}") from e
        gone = sorted(set(data) & set(GONE)) if isinstance(data, dict) else []
        if gone:
            raise ConfigError(f"{FILE}: {gone[0]} is no longer read: {GONE[gone[0]]}; take it out")
        if not isinstance(data, dict) or set(REQUIRED) - set(data) or set(data) - set(REQUIRED + OPTIONAL) \
                or not all(isinstance(data[k], str) for k in REQUIRED):
            raise ConfigError(f"{FILE} holds {', '.join(REQUIRED)} (strings) and may hold {', '.join(OPTIONAL)}")
        verify = data.get("verify", [])
        if "verify" in data and (not isinstance(verify, list) or not verify or not all(isinstance(w, str) for w in verify)):
            raise ConfigError(f"{FILE}: verify is a list of words, the test command")
        ledger = data.get("ledger", "")
        if "ledger" in data and not (isinstance(ledger, str) and Path(ledger).is_absolute()):
            raise ConfigError(f"{FILE}: ledger is the absolute path of the real ledger")
        return cls(data["name"], tuple(sys.executable if w == "{python}" else w for w in verify), ledger)
