"""Config: the one reader of .claude/project.json, the values of the user (config_net).
  name     the project's name
  verify   (optional) the test command of the unit, a list of words run in the plan's root; "{python}" is this Python
  protected (optional) the protected branches, names or fnmatch patterns; main and master when not given
  ledger   (optional) the absolute path of the real ledger, whose schema the doctor compares read only; a Windows
           path (C:/...) is absolute on every system, and on one that is not Windows it names no ledger here"""
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from harness.utils.git.branches import DEFAULT_PROTECTED

FILE = "project.json"
DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
REQUIRED = ("name",)
GONE = {"recipe": "the pipeline is picked by the state of the session (assemble/engine/select.py)"}
OPTIONAL = ("verify", "ledger", "protected")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    name: str
    verify: tuple = ()
    ledger: str = ""
    protected: tuple = DEFAULT_PROTECTED

    @property
    def ledger_here(self):
        """The real ledger's path on this system, or "": a Windows path names no file on another system."""
        return "" if os.name != "nt" and DRIVE.match(self.ledger) else self.ledger

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
        if "ledger" in data and not (isinstance(ledger, str) and (Path(ledger).is_absolute() or DRIVE.match(ledger))):
            raise ConfigError(f"{FILE}: ledger is the absolute path of the real ledger")
        protected = data.get("protected", list(DEFAULT_PROTECTED))
        if not isinstance(protected, list) or not protected or not all(isinstance(b, str) and b for b in protected):
            raise ConfigError(f"{FILE}: protected is a list of branch names or patterns (main, release/*)")
        return cls(data["name"], tuple(sys.executable if w == "{python}" else w for w in verify), ledger, tuple(protected))
