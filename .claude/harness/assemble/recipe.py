"""RecipeBook: which translators and detectors run, by name. A recipe may extend another and only adds to it, so an
overlay can make the harness stricter, never looser."""
import json
import re
from dataclasses import dataclass
from pathlib import Path

RECIPES_DIR = Path(__file__).with_name("recipes")
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
LISTS = ("translators", "detectors")
KEYS = ("about", "extends") + LISTS


class RecipeError(ValueError):
    pass


@dataclass(frozen=True)
class Recipe:
    name: str
    translators: tuple
    detectors: tuple


class RecipeBook:
    def __init__(self, recipes_dir=RECIPES_DIR):
        self.dir = Path(recipes_dir)

    def resolve(self, name, seen=()):
        if name in seen:
            raise RecipeError(f"recipe {name} extends itself through {' > '.join(seen)}")
        raw = self.read(name)
        base = self.resolve(raw["extends"], seen + (name,)) if raw.get("extends") else Recipe(name, (), ())
        lists = {k: tuple(dict.fromkeys(getattr(base, k) + tuple(raw.get(k, ())))) for k in LISTS}
        return Recipe(name, **lists)

    def read(self, name):
        if not isinstance(name, str) or not NAME.match(name):
            raise RecipeError(f"recipe name {name!r} is lower case letters, digits, - and _")
        path = self.dir / f"{name}.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            raise RecipeError(f"recipe {name} cannot be read: {e}") from e
        if not isinstance(raw, dict) or set(raw) - set(KEYS):
            raise RecipeError(f"recipe {name} holds only {', '.join(KEYS)}")
        for k in LISTS:
            if not isinstance(raw.get(k, []), list) or not all(isinstance(x, str) for x in raw.get(k, [])):
                raise RecipeError(f"recipe {name}: {k} is a list of names")
        if not isinstance(raw.get("extends", ""), str):
            raise RecipeError(f"recipe {name}: extends is the name of a recipe")
        return raw
