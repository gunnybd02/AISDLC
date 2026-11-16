"""PipelineBook: which translators and detectors run, by name, read from assemble/pipelines/<name>.json. A pipeline may
extend another and only adds to it, so a pipeline can make the harness stricter, never looser; select.py picks one."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

PIPELINES_DIR = Path(__file__).parents[1] / "pipelines"
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
LISTS = ("translators", "detectors")
KEYS = ("about", "extends") + LISTS


class PipelineError(ValueError):
    """A pipeline that cannot be read, is not of its shape, or extends itself."""


class PipelineFile(TypedDict, total=False):
    """A pipeline as its file holds it (assemble/pipelines/<name>.json): what it is for, the pipeline it extends, and
    the names of the translators and detectors it adds."""
    about: str
    extends: str
    translators: list[str]
    detectors: list[str]


@dataclass(frozen=True)
class Pipeline:
    name: str
    translators: tuple
    detectors: tuple


class PipelineBook:
    """The pipelines of a folder, read by name."""

    def __init__(self, pipelines_dir: str | Path = PIPELINES_DIR) -> None:
        """Keep the folder of the pipelines.

        Args:
            pipelines_dir: the folder of the <name>.json files.
        """
        self.dir = Path(pipelines_dir)

    def resolve(self, name: str, seen: tuple[str, ...] = ()) -> Pipeline:
        """The pipeline name with everything it extends, each name once, the base's first.

        Args:
            name: the pipeline's name.
            seen: the pipelines that extend it on the way here (to find a loop).

        Returns:
            The Pipeline with its translators and detectors.

        Raises:
            PipelineError: a pipeline on the way cannot be read, or extends itself.
        """
        if name in seen:
            raise PipelineError(f"pipeline {name} extends itself through {' > '.join(seen)}")
        raw = self.read(name)
        base = self.resolve(raw["extends"], seen + (name,)) if raw.get("extends") else Pipeline(name, (), ())
        lists = {k: tuple(dict.fromkeys(getattr(base, k) + tuple(raw.get(k, ())))) for k in LISTS}
        return Pipeline(name, **lists)

    def read(self, name: str) -> PipelineFile:
        """The file of one pipeline, checked.

        Args:
            name: the pipeline's name (lower case letters, digits, - and _).

        Returns:
            Its PipelineFile as written.

        Raises:
            PipelineError: a bad name, a file that does not read, or a key or value not of its shape.
        """
        if not isinstance(name, str) or not NAME.match(name):
            raise PipelineError(f"pipeline name {name!r} is lower case letters, digits, - and _")
        path = self.dir / f"{name}.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            raise PipelineError(f"pipeline {name} cannot be read: {e}") from e
        if not isinstance(raw, dict) or set(raw) - set(KEYS):
            raise PipelineError(f"pipeline {name} holds only {', '.join(KEYS)}")
        for k in LISTS:
            if not isinstance(raw.get(k, []), list) or not all(isinstance(x, str) for x in raw.get(k, [])):
                raise PipelineError(f"pipeline {name}: {k} is a list of names")
        if not isinstance(raw.get("extends", ""), str):
            raise PipelineError(f"pipeline {name}: extends is the name of a pipeline")
        return raw
