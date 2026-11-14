"""Tests of the mcp block. call() runs an action as the model does: through the real run tool, with the real ports of a
claude folder (a copy of the tree, so a write action meets the real judge)."""
from harness.assemble.engine.build import items_of
from harness.assemble.engine.wire_mcp import action_table, ports_of
from harness.mcp.tools.run import Run
from tests import CLAUDE_DIR


def caller(claude_dir):
    """call(block, action, **args) -> Result, run against the ports of claude_dir."""
    items = items_of(CLAUDE_DIR)
    run = Run(action_table(items), ports_of(items, claude_dir))
    return lambda block, action, **args: run.call({"block": block, "action": action, "args": args})
