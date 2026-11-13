"""The MCP door entry/mcp_server.py calls: run_mcp serves find, guide and run, over the action table. The actions are
the classes of mcp/actions/*.py; each gets only the ports it names in needs, built here."""
from pathlib import Path

from harness.assemble.engine.build import CLAUDE_DIR, BuildError, items_of
from harness.assemble.engine.checks import doctor, report
from harness.assemble.engine.config import Config
from harness.assemble.engine.loader import Loader
from harness.assemble.engine.ports import LedgerPort

SERVER = ("harness", "0.1")


def ports_of(items, claude_dir):
    """The ports an action may name in needs; a port that costs a read is a callable, read when the action runs."""
    ledger = LedgerPort(claude_dir)
    return {"plans": ledger, "ledger": ledger, "verify_command": lambda: Config.load(claude_dir).verify,
            "items": items, "doctor": lambda: report(doctor(claude_dir))}


def action_table(items, claude_dir, code_dir=CLAUDE_DIR):
    """The blocks run can reach: each action file of mcp/actions/ (read from code_dir, the tree whose code runs), its
    actions given their ports (from claude_dir, the tree whose state and config they use)."""
    table = Loader.resolve(items["action_table"])()
    ports = ports_of(items, claude_dir)
    for action_file in Loader(code_dir).action_files():
        table.add_block(action_file.block, action_file.about)
        for cls in Loader.actions(action_file):
            missing = sorted(set(cls.needs) - set(ports))
            if missing:
                raise BuildError(f"{action_file.module}.{cls.__name__} needs ports no one gives: {', '.join(missing)}")
            table.add(action_file.block, cls.name, cls.about, cls.args, cls({n: ports[n] for n in cls.needs}))
    return table


def run_mcp(instream, outstream, claude_dir=CLAUDE_DIR):
    """Serve find, guide and run over stdio until the input ends."""
    claude_dir = Path(claude_dir)
    items = items_of(claude_dir)
    table = action_table(items, claude_dir, claude_dir)
    skills = Loader.resolve(items["skills"])(claude_dir / "project" / "skills")
    tools = [Loader.resolve(items[n])(skills, table) for n in ("find", "guide")] + [Loader.resolve(items["run"])(table)]
    Loader.resolve(items["stdio"])(*SERVER, tools).serve(instream, outstream)
