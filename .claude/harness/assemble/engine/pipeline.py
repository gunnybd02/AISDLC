"""PipelineBook: which translators and detectors run, by name, read from assemble/pipelines/<name>.json. A pipeline may
extend another and only adds to it, so a pipeline can make the harness stricter, never looser; select.py picks one."""
import json
import re
from dataclasses import dataclass
from pathlib import Path

PIPELINES_DIR = Path(__file__).parents[1] / "pipelines"
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
LISTS = ("translators", "detectors")
KEYS = ("about", "extends") + LISTS


class PipelineError(ValueError):
    pass


@dataclass(frozen=True)
class Pipeline:
    name: str
    translators: tuple
    detectors: tuple


class PipelineBook:
    def __init__(self, pipelines_dir=PIPELINES_DIR):
        self.dir = Path(pipelines_dir)

    def resolve(self, name, seen=()):
        if name in seen:
            raise PipelineError(f"pipeline {name} extends itself through {' > '.join(seen)}")
        raw = self.read(name)
        base = self.resolve(raw["extends"], seen + (name,)) if raw.get("extends") else Pipeline(name, (), ())
        lists = {k: tuple(dict.fromkeys(getattr(base, k) + tuple(raw.get(k, ())))) for k in LISTS}
        return Pipeline(name, **lists)

    def read(self, name):
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
