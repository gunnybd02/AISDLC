"""run: call one action of the action table. Before it runs: the action exists, its arguments fit its args_schema, and
the server has every port it names in needs, which are all it is given. A write action is judged first: the judge
port answers the verdict of the rules for the call, and only an allow that a rule row decided lets it run (an ask too
is refused, the server cannot ask the user; an allow no rule decided is write-unjudged). A read is never judged."""
import os

from harness.mcp.actions.table import args_problem
from harness.mcp.server.tool import Result, Tool
from harness.utils.contracts import WRITE, ActionContext, ActionError, Event, judged_allow

TOOL = "mcp__harness__run"  # the name Claude Code gives this tool; the rules read it from the event
UNJUDGED = "write-unjudged: no rule decides this write, so it does not run; a rule row for it is needed first"


class Run(Tool):
    name = "run"
    description = "Run an action of a block: run(block, action, args). guide(block, 'mcp') lists the actions."
    schema = {"type": "object", "properties": {"block": {"type": "string"}, "action": {"type": "string"},
                                               "args": {"type": "object"}}, "required": ["block", "action"]}

    def __init__(self, table, ports):
        self.table, self.ports = table, ports

    def call(self, args):
        block, name, given = args.get("block"), args.get("action"), args.get("args", {})
        try:
            action = self.table.action(block, name)
        except (KeyError, TypeError):
            return Result(f"No action {block}.{name}; guide({block!r}, 'mcp') lists the actions.", True)
        problem = args_problem(action, given)
        if problem:
            return Result(problem, True)
        missing = [n for n in action.needs if n not in self.ports]
        if missing:
            return Result(f"{block}.{name} needs ports this server lacks: {', '.join(missing)}", True)
        if action.effect == WRITE:
            refused = self.judge(block, name, given)
            if refused:
                return Result(refused, True)
        try:
            return Result(str(action().run(ActionContext({n: self.ports[n] for n in action.needs}), given)))
        except (ActionError, ValueError) as e:
            return Result(str(e), True)

    def judge(self, block, name, given):
        """Why the write may not run, or ""."""
        judge = self.ports.get("judge")
        if judge is None:
            return f"{block}.{name} is a write and this server has no judge: it does not run"
        event = Event("PreToolUse", TOOL, {"block": block, "action": name, "args": given, "effect": WRITE}, "",
                      os.getcwd())
        try:
            verdict = judge(event)
        except Exception as e:
            return f"{block}.{name}: the judge failed ({type(e).__name__}: {e}), so the write does not run"
        if judged_allow(verdict):
            return ""
        return verdict.reason if verdict.findings else UNJUDGED
