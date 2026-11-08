"""The doors entry/ calls. Each builds what it needs from the tree: the loader gives the items of mcp and gear by
name, the config names the recipe, the recipe names the translators and detectors."""
from pathlib import Path

from harness.assemble.config import Config
from harness.assemble.loader import Loader
from harness.assemble.recipe import RecipeBook
from harness.assemble.runner import Runner
from nets import bridges_net, config_net, imports_net, layout_net, size_net, verdict_net

CLAUDE_DIR = Path(__file__).resolve().parents[2]
SERVER = ("harness", "0.1")
NETS = (layout_net, imports_net, bridges_net, size_net, verdict_net, config_net)


class BuildError(ValueError):
    pass


def pick(items, names, kind):
    """The objects of the named items, each checked to be of the kind the recipe needs."""
    out = []
    for name in names:
        item = items.get(name)
        if item is None or item.kind != kind:
            raise BuildError(f"the recipe names {name}, which is no {kind} of any block")
        out.append(Loader.resolve(item)())
    return out


def items_of(claude_dir):
    return {i.name: i for i in Loader(claude_dir).items()}


def build_runner(claude_dir=CLAUDE_DIR, items=None):
    claude_dir = Path(claude_dir)
    items = items or items_of(claude_dir)
    recipe = RecipeBook(claude_dir / "harness" / "assemble" / "recipes").resolve(Config.load(claude_dir).recipe)
    decide = Loader.resolve(items["decide"]).load(claude_dir)
    return Runner(pick(items, recipe.translators, "translator"), pick(items, recipe.detectors, "detector"), decide)


def run_hook(text, claude_dir=CLAUDE_DIR):
    """A hook payload in, Claude Code's answer out ("" when the call is allowed)."""
    items = items_of(claude_dir)
    hook_io = Loader.resolve(items["hook_io"])
    event = hook_io.read(text)
    return hook_io.write(event, build_runner(claude_dir, items).run(event))


def action_table(items, claude_dir):
    """The blocks run can reach. Their handlers live here, in assemble, so mcp stays a door that decides nothing."""
    table = Loader.resolve(items["action_table"])()
    table.add_block("health", "The health of the harness: what the blocks declare")
    table.add("health", "items", "The items of mcp and gear, one per line: block, kind, name", {},
              lambda: "\n".join(f"{i.block} {i.kind} {i.name}" for i in items.values()))
    table.add("health", "doctor", "Every problem of the tree: the indexes, the build, the nets", {},
              lambda: report(doctor(claude_dir)))
    return table


def doctor(claude_dir=CLAUDE_DIR):
    """The problems of the tree: the indexes, then the build (config, recipe, rules), then every net."""
    claude_dir = Path(claude_dir)
    problems = Loader(claude_dir).problems()
    if not problems:
        try:
            build_runner(claude_dir)
        except Exception as e:
            problems.append(f"build: {type(e).__name__}: {e}")
    for net in NETS:
        problems += net.check(claude_dir)
    return problems


def report(problems):
    return "\n".join([f"ERROR {p}" for p in problems] + [f"{len(problems)} errors"])


def run_mcp(instream, outstream, claude_dir=CLAUDE_DIR):
    """Serve find, guide and run over stdio until the input ends."""
    claude_dir = Path(claude_dir)
    items = items_of(claude_dir)
    table = action_table(items, claude_dir)
    skills = Loader.resolve(items["skills"])(claude_dir / "skills")
    tools = [Loader.resolve(items[n])(skills, table) for n in ("find", "guide")] + [Loader.resolve(items["run"])(table)]
    Loader.resolve(items["stdio"])(*SERVER, tools).serve(instream, outstream)
