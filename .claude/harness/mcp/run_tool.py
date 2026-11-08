"""run: call one action of the action table with its arguments; nothing outside the table can be called."""
from harness.mcp.tool import Result, Tool


class Run(Tool):
    name = "run"
    description = "Run an action of a block: run(block, action, args). guide(block, 'mcp') lists the actions."
    schema = {"type": "object", "properties": {"block": {"type": "string"}, "action": {"type": "string"},
                                               "args": {"type": "object"}}, "required": ["block", "action"]}

    def __init__(self, table):
        self.table = table

    def call(self, args):
        block, name, given = args.get("block"), args.get("action"), args.get("args", {})
        try:
            action = self.table.action(block, name)
        except KeyError:
            return Result(f"No action {block}.{name}; guide({block!r}, 'mcp') lists the actions.", True)
        problem = action.problem(given)
        if problem:
            return Result(problem, True)
        return Result(str(action.handler(**given)))
