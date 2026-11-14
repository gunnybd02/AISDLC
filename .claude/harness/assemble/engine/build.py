"""The hook door entry/hook.py calls: run_hook. It builds what it needs from the tree: the loader gives the items of
the blocks by name, select.py picks the pipeline by the session's plan, the pipeline names the translators and
detectors."""
import os
from dataclasses import replace
from pathlib import Path

from harness.assemble.engine.config import Config
from harness.assemble.engine.loader import Loader
from harness.assemble.engine.ports import LedgerPort, PlanState
from harness.assemble.engine.pipeline import PipelineBook
from harness.assemble.engine.runner import Act, Runner
from harness.assemble.engine.select import select
from harness.utils.contracts import Detector, Translator

CLAUDE_DIR = Path(__file__).resolve().parents[3]
CODE_ENV = "HARNESS_CODE"  # the release a session runs (entry/boot.py); unset: the home's own code


def code_of(claude_dir):
    """The folder whose code runs for the home claude_dir: the release boot chose, or the home itself."""
    return Path(os.environ.get(CODE_ENV) or claude_dir)
BASES = {"translator": Translator, "detector": Detector}
SHELL_HINT = (" (No mcp__harness__ tools in this session? The same from the shell: python3 \"{boot}\" cli tool run "
              "<block> <action> '<args as JSON>'; python3 \"{boot}\" cli tool guide <block> lists a block's actions.)")


class BuildError(ValueError):
    pass


def pick(items, names, kind):
    """An object of each named item, checked to be of the kind the pipeline needs and built on its base class."""
    out = []
    for name in names:
        item = items.get(name)
        cls = Loader.resolve(item) if item is not None and item.kind == kind else None
        if not (isinstance(cls, type) and issubclass(cls, BASES[kind])):
            raise BuildError(f"the pipeline names {name}, which is no {kind} of any block")
        out.append(cls())
    return out


def items_of(claude_dir):
    return {i.name: i for i in Loader(code_of(claude_dir)).items()}


def build_runner(claude_dir=CLAUDE_DIR, items=None, plan=None):
    """The runner of the pipeline select.py picks for a session working under plan (None: no plan, the floor)."""
    claude_dir = Path(claude_dir)
    items = items or items_of(claude_dir)
    config = Config.load(claude_dir)  # a config that does not load stops the hook, as before
    code = code_of(claude_dir)
    pipeline = select(PipelineBook(code / "harness" / "assemble" / "pipelines"), plan)
    decide = Loader.resolve(items["decide"]).load(code)
    port = LedgerPort(claude_dir)
    return Runner(pick(items, pipeline.translators, "translator"), pick(items, pipeline.detectors, "detector"), decide,
                  ports=[PlanState(port, config.protected, config.banned)], act=Act(port))


def with_hint(reason, claude_dir):
    """A reason that names run(...) also says how to call it from the shell (engine/cli_tool.py)."""
    if "run('" not in reason:
        return reason
    return reason + SHELL_HINT.format(boot=(Path(claude_dir) / "entry" / "boot.py").as_posix())


def run_hook(text, claude_dir=CLAUDE_DIR):
    """A hook payload in, Claude Code's answer out ("" when the call is allowed and there is nothing to say)."""
    items = items_of(claude_dir)
    hook_io = Loader.resolve(items["hook_io"])
    event = hook_io.read(text)
    outcome = build_runner(claude_dir, items, LedgerPort(claude_dir).approved(event.session)).run(event)
    verdict = replace(outcome.verdict, reason=with_hint(outcome.verdict.reason, claude_dir))
    return hook_io.write(event, verdict, outcome.notes)
