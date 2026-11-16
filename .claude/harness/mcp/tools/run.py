"""run: call one action of the action table. Every call leaves one span in the ledger (docs/12-ledger.md). Before it runs: the action exists, its arguments fit its args_schema, and
the server has every port it names in needs, which are all it is given. A write action is judged first: the judge
port answers the verdict of the rules for the call, and only an allow that a rule row decided lets it run (an ask too
is refused, the server cannot ask the user; an allow no rule decided is write-unjudged). A read is never judged."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from harness.mcp.actions.table import args_problem
from harness.mcp.server.tool import Result, Tool
from harness.utils.contracts import WRITE, ActionContext, ActionError, Event, judged_allow

if TYPE_CHECKING:
    from harness.mcp.actions.table import ActionTable

TOOL = "mcp__harness__run"  # the name Claude Code gives this tool; the rules read it from the event
UNJUDGED = "write-unjudged: no rule decides this write, so it does not run; a rule row for it is needed first"


class Run(Tool):
    """The run tool: one action of the action table, checked, and judged when it writes."""
    name = "run"
    description = "Run an action of a block: run(block, action, args). guide(block, 'mcp') lists the actions."
    schema = {"type": "object", "properties": {"block": {"type": "string"}, "action": {"type": "string"},
                                               "args": {"type": "object"}}, "required": ["block", "action"]}

    def __init__(self, table: ActionTable, ports: dict[str, Any]) -> None:
        """Keep the action table and the server's ports.

        Args:
            table: the actions run can reach.
            ports: the server's ports by name (ledger: a PlanStore, judge: judge(event) -> Verdict, git_judge,
                commit_judge...); each kind of port is its own type.
        """
        self.table, self.ports = table, ports

    def call(self, args: dict[str, Any]) -> Result:
        """Run the action {block, action, args?} and answer its text or its error (answer); the call leaves one span
        in the ledger, for success and for error, with the names of its arguments and never their values. A span that
        cannot be kept never changes the answer."""
        result = self.answer(args)
        ledger = self.ports.get("plans")
        if hasattr(ledger, "span"):
            given = args.get("args")
            ledger.span(self.ports.get("session"), "tool", "error" if result.is_error else "ok",
                        f"{args.get('block')}.{args.get('action')}",
                        {"args": sorted(str(k) for k in given) if isinstance(given, dict) else []})
        return result

    def answer(self, args: dict[str, Any]) -> Result:
        """Run the action {block, action, args?} with only the ports it needs, a write only when a rule allows it;
        answer its text, or an error for an unknown action, bad arguments, a missing port, a refused write or the
        action's ActionError or ValueError."""
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

    def judge(self, block: str, name: str, given: dict[str, Any]) -> str:
        """Why the write may not run, or "".

        Args:
            block: the action's block.
            name: the action's name.
            given: the action's arguments.

        Returns:
            "" when an allow a rule row decided lets it run; else why not: no judge port, the judge failed, the
            reason of the rules that ask or refuse, or UNJUDGED when no rule decided it.
        """
        judge = self.ports.get("judge")
        if judge is None:
            return f"{block}.{name} is a write and this server has no judge: it does not run"
        session = self.ports.get("session")
        event = Event("PreToolUse", TOOL, {"block": block, "action": name, "args": given, "effect": WRITE},
                      session() if callable(session) else "", os.getcwd())  # judged for the session that calls
        try:
            verdict = judge(event)
        except Exception as e:
            return f"{block}.{name}: the judge failed ({type(e).__name__}: {e}), so the write does not run"
        if judged_allow(verdict):
            return ""
        return verdict.reason if verdict.findings else UNJUDGED
