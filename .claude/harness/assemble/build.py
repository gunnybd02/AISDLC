"""The doors entry/ calls: run_hook, run_mcp, doctor. Each builds what it needs from the tree: the loader gives the items
of mcp and gear by name, the config names the recipe, the recipe names the translators and detectors."""
from pathlib import Path

from harness.assemble.act import Act
from harness.assemble.blocks import add_plan
from harness.assemble.config import Config
from harness.assemble.loader import Loader
from harness.assemble.ports import LedgerPort, PlanState
from harness.assemble.recipe import RecipeBook
from harness.assemble.runner import Runner
from harness.utils.contracts import Detector, Translator

CLAUDE_DIR = Path(__file__).resolve().parents[2]
SERVER = ("harness", "0.1")
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
    recipe = RecipeBook(claude_dir / "harness" / "assemble" / "recipes").resolve(Config.load(claude_dir).recipe)
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


def action_table(items, claude_dir):
    """The blocks run can reach. Their handlers live in assemble, so mcp stays a door that decides nothing."""
    table = Loader.resolve(items["action_table"])()
    add_plan(table, LedgerPort(claude_dir))
    table.add_block("health", "The health of the harness: what the blocks declare")
    table.add("health", "items", "The items of mcp and gear, one per line: block, kind, name", {},
              lambda: "\n".join(f"{i.block} {i.kind} {i.name}" for i in items.values()))
    table.add("health", "doctor", "Every problem of the tree: the indexes, the build, the skills, the nets", {},
              lambda: report(doctor(claude_dir)))
    return table


def run_mcp(instream, outstream, claude_dir=CLAUDE_DIR):
    """Serve find, guide and run over stdio until the input ends."""
    claude_dir = Path(claude_dir)
    items = items_of(claude_dir)
    table = action_table(items, claude_dir)
    skills = Loader.resolve(items["skills"])(claude_dir / "skills")
    tools = [Loader.resolve(items[n])(skills, table) for n in ("find", "guide")] + [Loader.resolve(items["run"])(table)]
    Loader.resolve(items["stdio"])(*SERVER, tools).serve(instream, outstream)


def doctor(claude_dir=CLAUDE_DIR):
    """Every problem of the tree: the indexes, each item's ref, the build (config, recipe, rules), the skills, the nets.
    The nets are dev-time code, imported here only, so they never weigh on a hook call."""
    from nets import bridges_net, config_net, entry_net, imports_net, layout_net, size_net, verdict_net
    claude_dir = Path(claude_dir)
    problems = Loader(claude_dir).problems()
    if not problems:
        problems += built(claude_dir)
    for net in (layout_net, imports_net, bridges_net, size_net, verdict_net, config_net, entry_net):
        problems += net.check(claude_dir)
    return problems


def built(claude_dir):
    """What fails when the tree is put together: a ref that does not load, the build, the skill library."""
    out, items = [], items_of(claude_dir)
    for item in items.values():
        try:
            Loader.resolve(item)
        except Exception as e:
            out.append(f"item {item.name}: {item.ref} does not load ({type(e).__name__}: {e})")
    if out:
        return out
    try:
        build_runner(claude_dir, items)
        out += Loader.resolve(items["skills"])(claude_dir / "skills").problems()
    except Exception as e:
        out.append(f"build: {type(e).__name__}: {e}")
    return out


def report(problems):
    return "\n".join([f"ERROR {p}" for p in problems] + [f"{len(problems)} errors"])
