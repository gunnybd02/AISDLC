"""Config: the one reader of .claude/project.json, the values of the user (config_net).
  name     the project's name
  verify   (optional) the test command of the unit, a list of words run in the plan's root; "{python}" is this Python
  banned   (optional) words commit and merge request text never hold
  protected (optional) the protected branches, names or fnmatch patterns; main and master when not given
  ledger   (optional) the absolute path of the real ledger, whose schema the doctor compares read only; a Windows
           path (C:/...) is absolute on every system, and on one that is not Windows it names no ledger here
  units    (optional) the projects a plan or a child of a delegated plan works on, by name (a-z, 0-9, -):
           {"api": {"repo": "https://github.com/me/shop", "path": "services/api", "verify": [...], "base": "main"}}
           repo its repository (https; "" or none: the home's own), path its folder in it (default "."), verify its
           test command run in that folder (default: verify above), base the branch its pull requests target
           (default "main"), pipeline (optional) the pipeline a plan on it runs on top of the floor
           (assemble/pipelines/<name>.json, spec 13 section 11.6). Several units may share one repository, each with
           its own path (a repo of many units).
  limits   (optional) the orchestra's policy limits, each a whole number from 1 to 10: {"children": 3, "rounds": 3}
           children the children of a delegated plan that run at once, rounds the send-backs of one child before the
           user decides. A limit not given is its default (LIMITS, spec 05)."""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from harness.utils.git.branches import DEFAULT_PROTECTED

FILE = "project.json"
DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
REQUIRED = ("name",)
GONE = {"recipe": "the pipeline is picked by the state of the session (assemble/engine/select.py)"}
OPTIONAL = ("verify", "ledger", "protected", "banned", "units", "limits")
LIMITS = {"children": 3, "rounds": 3}  # the defaults; the one place the values live (owners)
UNIT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
RESERVED = ("home", "none", "agent-code")
UNIT_KEYS = ("repo", "path", "verify", "base", "pipeline")
PIPELINE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")  # as assemble/engine/pipeline.py reads a name


class ConfigError(ValueError):
    """The config cannot be read, or holds a value it may not."""


@dataclass(frozen=True)
class Unit:
    """A project the plans and children work on (units in project.json): its repository URL ("" for the home's own),
    its folder in it, its test command (words; "{python}" kept, filled where it runs), the branch its pull
    requests target, and the pipeline a plan on it adds to the floor ("" for none)."""
    repo: str = ""
    path: str = "."
    verify: tuple = ()
    base: str = "main"
    pipeline: str = ""

    def spec(self) -> dict[str, object]:
        """The unit as a card carries it to a child: {repo, path, verify, base}.

        Returns:
            The plain dict, verify as a list.
        """
        return {"repo": self.repo, "path": self.path, "verify": list(self.verify), "base": self.base}


def unit_of(name: str, value: object, verify: tuple) -> Unit:
    """Check one entry of units and make its Unit.

    Args:
        name: the unit's name.
        value: its entry in project.json.
        verify: the config's own verify, the unit's when it names none.

    Returns:
        The Unit.

    Raises:
        ConfigError: a bad name or a value not of its shape.
    """
    where = f"{FILE}: units.{name}"
    if not UNIT_NAME.match(name) or name in RESERVED:
        raise ConfigError(f"{where}: a unit's name is a-z, 0-9 and -, not {', '.join(RESERVED)}")
    if not isinstance(value, dict) or set(value) - set(UNIT_KEYS):
        raise ConfigError(f"{where} holds only {', '.join(UNIT_KEYS)}")
    repo, path, base = value.get("repo", ""), value.get("path", "."), value.get("base", "main")
    if not isinstance(repo, str) or (repo and not re.match(r"^https://[^\s@]+$", repo)):
        raise ConfigError(f"{where}: repo is the https URL of its repository, or \"\" for the home's own")
    parts = re.split(r"[\\/]", path) if isinstance(path, str) else [".."]
    if not path or ".." in parts or Path(path).is_absolute() or DRIVE.match(path):
        raise ConfigError(f"{where}: path is a folder inside its repository (no .., not absolute)")
    words = value.get("verify", list(verify))
    if not isinstance(words, list) or not all(isinstance(w, str) for w in words) or ("verify" in value and not words):
        raise ConfigError(f"{where}: verify is a list of words, its test command")
    if not isinstance(base, str) or not re.match(r"^[A-Za-z0-9._/-]+$", base):
        raise ConfigError(f"{where}: base is a branch name")
    pipeline = value.get("pipeline", "")
    if not isinstance(pipeline, str) or (pipeline and not PIPELINE_NAME.match(pipeline)):
        raise ConfigError(f"{where}: pipeline is the name of a pipeline (lower case letters, digits, - and _)")
    return Unit(repo, path.replace("\\", "/").strip("/") or ".", tuple(words), base, pipeline)


def limits_of(value: object) -> tuple:
    """Check the limits of the config and fill in the defaults.

    Args:
        value: the limits object of project.json ({} when it has none).

    Returns:
        ((name, value), ...) for every limit of LIMITS.

    Raises:
        ConfigError: not an object, an unknown limit, or a value that is not a whole number from 1 to 10.
    """
    if not isinstance(value, dict) or set(value) - set(LIMITS):
        raise ConfigError(f"{FILE}: limits is an object of {', '.join(LIMITS)}")
    for name, n in value.items():
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 10:
            raise ConfigError(f"{FILE}: limits.{name} is a whole number from 1 to 10")
    return tuple((name, value.get(name, default)) for name, default in LIMITS.items())


@dataclass(frozen=True)
class Config:
    name: str
    verify: tuple = ()
    ledger: str = ""
    protected: tuple = DEFAULT_PROTECTED
    banned: tuple = ()
    units: tuple = ()  # ((name, Unit), ...), in the file's order
    limits: tuple = tuple(LIMITS.items())  # ((name, value), ...), every limit, the defaults filled in

    @property
    def ledger_here(self) -> str:
        """The real ledger's path on this system, or "": a Windows path names no file on another system.

        Returns:
            The ledger path, or "" when none is named or it is a Windows path here on another system.
        """
        return "" if os.name != "nt" and DRIVE.match(self.ledger) else self.ledger

    @classmethod
    def load(cls, claude_dir: str | Path) -> Config:
        """Read and check the config of the home.

        Args:
            claude_dir: the home, the .claude folder that holds project.json.

        Returns:
            The Config; verify's "{python}" is this Python, banned words are stripped.

        Raises:
            ConfigError: the file cannot be read, names a key no longer read, or a value is not of its shape.
        """
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
        banned = data.get("banned", [])
        if not isinstance(banned, list) or not all(isinstance(w, str) and w.strip() for w in banned):
            raise ConfigError(f"{FILE}: banned is a list of words commit and merge request text never hold")
        units = data.get("units", {})
        if not isinstance(units, dict):
            raise ConfigError(f"{FILE}: units is an object of units by name")
        made = tuple((name, unit_of(name, value, tuple(verify))) for name, value in units.items())
        return cls(data["name"], tuple(sys.executable if w == "{python}" else w for w in verify), ledger,
                   tuple(protected), tuple(w.strip() for w in banned), made, limits_of(data.get("limits", {})))

    def pipelines(self) -> dict[str, str]:
        """The units that name a pipeline, and the pipeline each names.

        Returns:
            {unit name: pipeline name}.
        """
        return {name: unit.pipeline for name, unit in self.units if unit.pipeline}

    def unit(self, name: str) -> Optional[Unit]:
        """A declared unit by its name.

        Args:
            name: the unit's name.

        Returns:
            The Unit, or None when the config declares none of that name.
        """
        return dict(self.units).get(name)
