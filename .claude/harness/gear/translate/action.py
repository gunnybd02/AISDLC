"""Actions: the facts of a call of the harness's run tool that says it writes (mcp/tools/run.py builds that event for a
write action before it runs; Claude Code names the tool mcp__harness__run). action_write is "block.name"."""
from harness.utils.contracts import WRITE, Translator

RUN_TOOLS = ("mcp__harness__run",)


class Actions(Translator):
    def translate(self, event):
        data = event.input
        if event.tool not in RUN_TOOLS or data.get("effect") != WRITE:
            return {}
        block, name = data.get("block"), data.get("action")
        return {"action_write": f"{block}.{name}"} if isinstance(block, str) and isinstance(name, str) else {}
