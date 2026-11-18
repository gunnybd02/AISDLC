"""The doctor door harness/entry/doctor.py calls: every problem of the tree, and the report of them."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from harness.assemble.engine.build import CLAUDE_DIR, build_runner, code_of, items_of, skill_docs
from harness.assemble.engine.loader import Loader
from harness.assemble.engine.pipeline import PipelineBook
from harness.assemble.engine.ports import SERVER_PORTS
from harness.utils.contracts import EFFECTS, McpAction
from harness.utils.ledger.db import compare_real


def doctor(claude_dir: str | Path = CLAUDE_DIR) -> list[str]:
    """Every problem of the tree: the indexes, each item's ref, the build (pipeline, rules), the skills, the real
    ledger's schema, the hash chains of the home's ledger, the nets. The nets are dev-time code, imported here only, so
    they never weigh on a hook call.

    Args:
        claude_dir: the home, the .claude folder; the nets read the code that runs (code_of).

    Returns:
        One line per problem; [] when the tree is clean.
    """
    from harness.nets import (bridges_net, english_net, entry_net, hints_net, imports_net, layout_net, owners_net,
                              size_net, verdict_net)
    claude_dir = Path(claude_dir)
    problems = Loader(code_of(claude_dir)).problems()
    if not problems:
        problems += built(claude_dir) + pipelines(claude_dir)
    problems += real_ledger(claude_dir)
    problems += chains(claude_dir)
    for net in (layout_net, imports_net, bridges_net, size_net, verdict_net, entry_net, hints_net, owners_net,
                english_net):
        problems += net.check(code_of(claude_dir))
    return problems


def pipelines(claude_dir: Path) -> list[str]:
    """Every pipeline file that does not read, names extends, or names a gear no block declares (spec 13 section 7).
    A plan's repo that names a pipeline with no file is refused when the hook builds its runner.

    Args:
        claude_dir: the home, the .claude folder.

    Returns:
        "pipeline <name>: ..." lines.
    """
    items = items_of(claude_dir)
    known = {"translators": {n for n, i in items.items() if i.kind == "translator"},
             "detectors": {n for n, i in items.items() if i.kind == "detector"}}
    return PipelineBook(code_of(claude_dir) / "harness" / "assemble" / "pipelines").problems(known)


def built(claude_dir: Path) -> list[str]:
    """What fails when the tree is put together: a ref that does not load, the build, the skill library (a skill
    that does not read, or names an action, a block or a skill that is not there).

    Args:
        claude_dir: the home, the .claude folder.

    Returns:
        One line per problem; the build is tried only when every ref and action file loads.
    """
    out, items, actions = [], items_of(claude_dir), []
    for item in items.values():
        try:
            Loader.resolve(item)
        except Exception as e:
            out.append(f"item {item.name}: {item.ref} does not load ({type(e).__name__}: {e})")
    for action_file in Loader(code_of(claude_dir)).action_files():
        try:
            entries = Loader.actions(action_file)
            out += [f"actions {action_file.module}: {p}" for p in action_problems(entries)]
            actions += [f"{block}.{name}" for block, name, _ in entries]
        except Exception as e:
            out.append(f"actions {action_file.module} do not load ({type(e).__name__}: {e})")
    if out:
        return out
    try:
        build_runner(claude_dir, items)
        skills = Loader.resolve(items["skills"])(skill_docs(claude_dir))
        out += skills.problems() + skills.stale(actions)
    except Exception as e:
        out.append(f"build: {type(e).__name__}: {e}")
    return out


def chains(claude_dir: str | Path) -> list[str]:
    """The broken hash chains of the home's own ledger, read only; a home with no ledger, or one that cannot be read
    now, has none to report.

    Args:
        claude_dir: the home, the .claude folder.

    Returns:
        "ledger: <table> row <n> breaks its hash chain ..." per chained table whose chain is not whole.
    """
    import sqlite3
    from harness.utils.ledger.recorder import chain_report
    path = Path(claude_dir) / "state" / "harness.db"
    if not path.is_file():
        return []
    try:
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            report = chain_report(con)
        finally:
            con.close()
    except sqlite3.Error:
        return []
    return [f"ledger: {table} row {row} breaks its hash chain (a row was changed after it was written)"
            for table, _, row in report if row is not None]


def real_ledger(claude_dir: str | Path) -> list[str]:
    """The drift of the real ledger from schema.sql, read only: the one HARNESS_LEDGER names (the user's PC); nothing
    when none is named. A Windows path names no file on another system.

    Args:
        claude_dir: the home, the .claude folder (not read).

    Returns:
        "ledger <drift>" lines.
    """
    path = os.environ.get("HARNESS_LEDGER", "").strip()
    if path and os.name != "nt" and re.match(r"^[A-Za-z]:[\\/]", path):
        path = ""
    return [f"ledger {line}" for line in compare_real(path)] if path else []


def report(problems: list[str]) -> str:
    """The doctor's report: an ERROR line per problem, then the count.

    Args:
        problems: the problems (doctor).

    Returns:
        "ERROR <problem>" lines and "<n> errors".
    """
    return "\n".join([f"ERROR {p}" for p in problems] + [f"{len(problems)} errors"])


def action_problems(entries: list[tuple[str, str, Any]]) -> list[str]:
    """What is wrong with the (block, name, class) entries of an action file: a class that is no McpAction, a block or
    name other than its entry's, an effect other than read or write, a port in needs no server gives.

    Args:
        entries: (block, name, the object the file holds under the class name) of each entry (Loader.actions).

    Returns:
        "<block>.<name>: <what is wrong>" lines.
    """
    out = []
    for block, name, cls in entries:
        what = f"{block}.{name}"
        if not (isinstance(cls, type) and issubclass(cls, McpAction)):
            out.append(f"{what}: {getattr(cls, '__name__', cls)} is no McpAction")
            continue
        if (cls.block, cls.name) != (block, name):
            out.append(f"{what}: the class says {cls.block}.{cls.name}")
        if cls.effect not in EFFECTS:
            out.append(f"{what}: effect {cls.effect!r} is not one of {', '.join(EFFECTS)}")
        missing = [n for n in cls.needs if n not in SERVER_PORTS]
        if missing:
            out.append(f"{what} needs ports no server gives: {', '.join(missing)}")
    return out
