"""The hook door entry/hook.py calls: run_hook. It builds what it needs from the tree: the loader gives the items of
the blocks by name, the config names the recipe, the recipe names the translators and detectors."""
from pathlib import Path

from harness.assemble.engine.config import Config
from harness.assemble.engine.loader import Loader
from harness.assemble.engine.ports import LedgerPort, PlanState
from harness.assemble.engine.pipeline import RecipeBook
from harness.assemble.engine.runner import Act, Runner
from harness.utils.contracts import Detector, Translator

CLAUDE_DIR = Path(__file__).resolve().parents[3]
BASES = {"translator": Translator, "detector": Detector}


class BuildError(ValueError):
    pass


def pick(items, names, kind):
    """An object of each named item, checked to be of the kind the recipe needs and built on its base class."""
    out = []
    for name in names:
        item = items.get(name)
        cls = Loader.resolve(item) if item is not None and item.kind == kind else None
        if not (isinstance(cls, type) and issubclass(cls, BASES[kind])):
            raise BuildError(f"the recipe names {name}, which is no {kind} of any block")
        out.append(cls())
    return out


def items_of(claude_dir):
    return {i.name: i for i in Loader(claude_dir).items()}


def build_runner(claude_dir=CLAUDE_DIR, items=None):
    claude_dir = Path(claude_dir)
    items = items or items_of(claude_dir)
    recipe = RecipeBook(claude_dir / "harness" / "assemble" / "pipelines").resolve(Config.load(claude_dir).recipe)
    decide = Loader.resolve(items["decide"]).load(claude_dir)
    port = LedgerPort(claude_dir)
    return Runner(pick(items, recipe.translators, "translator"), pick(items, recipe.detectors, "detector"), decide,
                  ports=[PlanState(port)], act=Act(port))


def run_hook(text, claude_dir=CLAUDE_DIR):
    """A hook payload in, Claude Code's answer out ("" when the call is allowed and there is nothing to say)."""
    items = items_of(claude_dir)
    hook_io = Loader.resolve(items["hook_io"])
    event = hook_io.read(text)
    outcome = build_runner(claude_dir, items).run(event)
    return hook_io.write(event, outcome.verdict, outcome.notes)
