"""The hook door harness/entry/hook.py calls: run_hook. It builds what it needs from the tree: the loader gives the items of
the blocks by name, select.py picks the pipeline by the session's plan, the pipeline names the translators and
detectors."""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Optional

from harness.assemble.engine.config import Config
from harness.assemble.engine.loader import Item, Loader
from harness.assemble.engine.ports import LedgerPort, PlanState
from harness.assemble.engine.pipeline import PipelineBook
from harness.assemble.engine.runner import Act, Runner
from harness.assemble.engine.select import select
from harness.utils.contracts import Detector, Translator
from harness.utils.gateway.release import anchor
from harness.utils.shapes import ApprovedPlan

CLAUDE_DIR = Path(__file__).resolve().parents[3]
CODE_ENV = "HARNESS_CODE"  # the release a session runs (anchor.py); unset: the home's own code


def code_of(claude_dir: str | Path) -> Path:
    """The folder whose code runs for the home claude_dir: the release boot chose, or the home itself.

    Args:
        claude_dir: the home, the .claude folder (state, config).

    Returns:
        HARNESS_CODE when set (a release folder), else claude_dir.
    """
    return Path(os.environ.get(CODE_ENV) or claude_dir)


def skill_docs(claude_dir: str | Path) -> Path:
    """The folder of the skill texts (<name>/SKILL.md) of the code that runs: part of a release, as its rules are.

    Args:
        claude_dir: the home, the .claude folder.

    Returns:
        harness/mcp/skill_docs of the code that runs (code_of).
    """
    return code_of(claude_dir) / "harness" / "mcp" / "skill_docs"


BASES = {"translator": Translator, "detector": Detector}
SHELL_HINT = (" (No mcp__harness__ tools in this session? The same from the shell: python3 \"{boot}\" cli tool run "
              "<block> <action> '<args as JSON>'; python3 \"{boot}\" cli tool guide <block> lists a block's actions.)")


class BuildError(ValueError):
    """The pipeline names something that is no translator or detector of any block."""


def pick(items: dict[str, Item], names: tuple[str, ...], kind: str) -> list[Any]:
    """An object of each named item, checked to be of the kind the pipeline needs and built on its base class.

    Args:
        items: the items of the blocks by name (items_of).
        names: the names the pipeline lists, in order.
        kind: translator or detector.

    Returns:
        A new object of each named class, in order: Translators or Detectors, as kind says.

    Raises:
        BuildError: a name is no item of that kind, or its class is not built on the kind's base class.
    """
    out = []
    for name in names:
        item = items.get(name)
        cls = Loader.resolve(item) if item is not None and item.kind == kind else None
        if not (isinstance(cls, type) and issubclass(cls, BASES[kind])):
            raise BuildError(f"the pipeline names {name}, which is no {kind} of any block")
        out.append(cls())
    return out


def items_of(claude_dir: str | Path) -> dict[str, Item]:
    """The items of the hooks, mcp and gear blocks of the code that runs, by name.

    Args:
        claude_dir: the home, the .claude folder.

    Returns:
        {item name: Item}.

    Raises:
        LoaderError: an index of a block is not a plain declaration.
    """
    return {i.name: i for i in Loader(code_of(claude_dir)).items()}


def build_runner(claude_dir: str | Path = CLAUDE_DIR, items: Optional[dict[str, Item]] = None,
                 plan: Optional[ApprovedPlan] = None) -> Runner:
    """The runner of the pipeline select.py picks for a session working under plan (None: no plan, the floor).

    Args:
        claude_dir: the home, the .claude folder (its config and ledger).
        items: the items by name, when the caller has them already; None reads them.
        plan: the plan in force in the session, or None.

    Returns:
        A Runner with the pipeline's translators and detectors, the decide of gear, PlanState and Act on the ledger.

    Raises:
        ConfigError: the config does not load.
        PipelineError: the floor or a pipeline of the plan's units cannot be read.
        BuildError: the pipeline names something that is no translator or detector.
    """
    claude_dir = Path(claude_dir)
    items = items or items_of(claude_dir)
    config = Config.load(claude_dir)  # a config that does not load stops the hook, as before
    code = code_of(claude_dir)
    pipeline = select(PipelineBook(code / "harness" / "assemble" / "pipelines"), plan, config.pipelines())
    translators = pick(items, pipeline.translators, "translator")
    declared = pick(items, [n for n, i in items.items() if i.kind == "translator"], "translator")
    vocabulary = {fact for t in declared for fact in getattr(t, "VOCABULARY", ())}  # rules apply to every pipeline
    decide = Loader.resolve(items["decide"]).load(code, vocabulary=vocabulary)
    port = LedgerPort(claude_dir)
    return Runner(translators, pick(items, pipeline.detectors, "detector"), decide,
                  ports=[PlanState(port, config.protected, config.banned)], act=Act(port))


def with_hint(reason: str, claude_dir: str | Path) -> str:
    """A reason that names run(...) also says how to call it from the shell (engine/cli_tool.py).

    Args:
        reason: the reason of a verdict.
        claude_dir: the home, whose anchor the hint names.

    Returns:
        The reason, with the shell hint added when it names run('.
    """
    if "run('" not in reason:
        return reason
    return reason + SHELL_HINT.format(boot=anchor(claude_dir).as_posix())


def run_hook(text: str, claude_dir: str | Path = CLAUDE_DIR) -> str:
    """A hook payload in, Claude Code's answer out ("" when the call is allowed and there is nothing to say).

    Args:
        text: the hook's JSON payload as Claude Code sent it on stdin.
        claude_dir: the home, the .claude folder.

    Returns:
        The JSON text for stdout, or "".
    """
    items = items_of(claude_dir)
    hook_io = Loader.resolve(items["hook_io"])
    event = hook_io.read(text)
    outcome = build_runner(claude_dir, items, LedgerPort(claude_dir).approved(event.session)).run(event)
    verdict = replace(outcome.verdict, reason=with_hint(outcome.verdict.reason, claude_dir))
    return hook_io.write(event, verdict, outcome.notes)
