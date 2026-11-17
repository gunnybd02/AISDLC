"""PipelineBook: which translators and detectors run, by name, read from assemble/pipelines/<name>.json. A pipeline
stands alone (spec 13 section 7): its file holds only its own lists and never names another pipeline. The floor (base)
runs under every event; select.py puts it under a plan's pipeline, so a pipeline can only add to the floor."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

PIPELINES_DIR = Path(__file__).parents[1] / "pipelines"
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
LISTS = ("translators", "detectors")
KEYS = ("about",) + LISTS
GONE = {"extends": "extends is not allowed: a pipeline is self-contained; the floor runs under it by itself"}


class PipelineError(ValueError):
    """A pipeline that cannot be read, or is not of its shape."""


class PipelineFile(TypedDict, total=False):
    """A pipeline as its file holds it (assemble/pipelines/<name>.json): what it is for, and the names of the translators
    and detectors it runs (for a plan's pipeline: those it adds to the floor)."""
    about: str
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

    def resolve(self, name: str) -> Pipeline:
        """The pipeline of a name, as its file holds it (each name once).

        Args:
            name: the pipeline's name.

        Returns:
            The Pipeline with its translators and detectors.

        Raises:
            PipelineError: its file cannot be read or is not of its shape.
        """
        raw = self.read(name)
        return Pipeline(name, **{k: tuple(dict.fromkeys(raw.get(k, ()))) for k in LISTS})

    def names(self) -> list[str]:
        """The names of the pipeline files of the folder.

        Returns:
            Their names, sorted.
        """
        return sorted(p.stem for p in self.dir.glob("*.json"))

    def problems(self, known: dict[str, set[str]]) -> list[str]:
        """Every pipeline file that does not read, or names a gear no block declares (the doctor's check).

        Args:
            known: {"translators": names, "detectors": names} the blocks declare.

        Returns:
            "pipeline <name>: ..." lines; [] when every file is good.
        """
        out = []
        for name in self.names():
            try:
                pipeline = self.resolve(name)
            except PipelineError as e:
                out.append(str(e))
                continue
            for kind in LISTS:
                out += [f"pipeline {name}: unknown {kind[:-1]} {n}" for n in getattr(pipeline, kind)
                        if n not in known.get(kind, set())]
        return out

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
        gone = sorted(set(raw) & set(GONE)) if isinstance(raw, dict) else []
        if gone:
            raise PipelineError(f"pipeline {name}: {GONE[gone[0]]}")
        if not isinstance(raw, dict) or set(raw) - set(KEYS):
            raise PipelineError(f"pipeline {name} holds only {', '.join(KEYS)}")
        for k in LISTS:
            if not isinstance(raw.get(k, []), list) or not all(isinstance(x, str) for x in raw.get(k, [])):
                raise PipelineError(f"pipeline {name}: {k} is a list of names")
        return raw
