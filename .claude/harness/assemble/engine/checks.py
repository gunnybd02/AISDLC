"""The doctor door entry/doctor.py calls: every problem of the tree, and the report of them."""
from pathlib import Path

from harness.assemble.engine.build import CLAUDE_DIR, build_runner, items_of
from harness.assemble.engine.config import Config, ConfigError
from harness.assemble.engine.loader import Loader
from harness.utils.ledger.db import compare_real


def doctor(claude_dir=CLAUDE_DIR):
    """Every problem of the tree: the indexes, each item's ref, the build (config, recipe, rules), the skills, the real
    ledger's schema, the nets. The nets are dev-time code, imported here only, so they never weigh on a hook call."""
    from nets import bridges_net, config_net, entry_net, imports_net, layout_net, size_net, verdict_net
    claude_dir = Path(claude_dir)
    problems = Loader(claude_dir).problems()
    if not problems:
        problems += built(claude_dir)
    problems += real_ledger(claude_dir)
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
        out += Loader.resolve(items["skills"])(claude_dir / "project" / "skills").problems()
    except Exception as e:
        out.append(f"build: {type(e).__name__}: {e}")
    return out


def real_ledger(claude_dir):
    """The drift of the real ledger named in the config from schema.sql, read only; nothing when none is named, or
    when the config does not load (built() reports that)."""
    try:
        path = Config.load(claude_dir).ledger
    except ConfigError:
        return []
    return [f"ledger {line}" for line in compare_real(path)] if path else []


def report(problems):
    return "\n".join([f"ERROR {p}" for p in problems] + [f"{len(problems)} errors"])
