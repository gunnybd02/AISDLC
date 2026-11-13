"""The MCP door entry/mcp_server.py calls: run_mcp serves find, guide and run, over the action table."""
from pathlib import Path

from harness.assemble.engine.blocks import add_harness, add_plan, add_verify
from harness.assemble.engine.build import CLAUDE_DIR, items_of
from harness.assemble.engine.checks import doctor, report
from harness.assemble.engine.loader import Loader
from harness.assemble.engine.ports import LedgerPort

SERVER = ("harness", "0.1")


def action_table(items, claude_dir):
    """The blocks run can reach. Their handlers live in assemble, so mcp stays a door that decides nothing."""
    table = Loader.resolve(items["action_table"])()
    port = LedgerPort(claude_dir)
    add_plan(table, port)
    add_verify(table, port, claude_dir)
    add_harness(table, claude_dir)
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
    skills = Loader.resolve(items["skills"])(claude_dir / "project" / "skills")
    tools = [Loader.resolve(items[n])(skills, table) for n in ("find", "guide")] + [Loader.resolve(items["run"])(table)]
    Loader.resolve(items["stdio"])(*SERVER, tools).serve(instream, outstream)
