---
name: harness-action
description: Develop the harness - add an action to a tool block that the model runs with run(block, action, args), with its schema, ports, effect, rule row and tests.
---
# Harness action
An action is one class the `run` tool reaches. A block is only the first part of its name.

## When to use
- To give the model a new thing to do or read through the harness.

## Steps
1. Write the test first: `harness/tests/mcp/test_<module>.py` for the action file `mcp/actions/<module>.py`.
2. The class, in a file of `mcp/actions/`:
   ```python
   from harness.utils.contracts import READ, ActionError, McpAction

   ACTIONS = [("notes.list", "List")]

   class List(McpAction):
       block, name, effect = "notes", "list", READ
       summary = "The notes of the session, newest first"
       args_schema = {"type": "object", "properties": {"limit": {"type": "integer"}}, "required": []}
       needs = ("ledger",)

       def run(self, ctx, args):
           if args.get("limit", 1) < 1:
               raise ActionError("limit is 1 or more")
           return "..."
   ```
   - `ACTIONS` is one literal list; the loader reads it from the syntax tree.
   - `summary` is what `find` and `guide` show: say what it does and when it is refused.
   - `needs` names ports of `ACTION_PORTS` (`assemble/engine/ports.py`); the action gets only those, in `ctx.ports`.
   - `run` returns text for the model; `ActionError` is how it says no.
3. A `write` action is judged before it runs: add its row to `gear/rules/actions.json`.
   ```json
   {"finding": "action.notes.add", "verdict": "allow", "why": "<why it is safe to run>",
    "test": "harness/tests/gear/test_action.py#test_each_write_action_of_the_server_has_its_rule"}
   ```
   Without the row the action never runs. A `read` action is never judged.
4. Pin it: add `"notes.list": READ` to `PINNED` in `harness/tests/mcp/test_action_registry.py`.
5. Logic bigger than a few lines goes to `utils/` (no policy there); the action only checks arguments and calls it.
6. A new port: build it in `assemble/engine/wire_mcp.py` and name it in `ACTION_PORTS`.
7. Tests and the doctor clean (`guide("harness-map", "skills")`), then name the action in the skill that uses it.

## Notes
- An action that needs the user's word answers with a form question and keeps a one-use pass
  (`utils/git/asks.py`); the model asks the form and runs the action again. See `mr_open` in `utils/plan/ship.py`.
- An action with an effect outside the ledger (git, the network) makes every check before it acts.
- The doctor refuses a skill that names an action that does not exist: keep the skills in step.
