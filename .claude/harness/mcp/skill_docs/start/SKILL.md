---
name: start
description: Start here in every session - how to work under the harness, its tools find guide run, the order of work, and the list of skills.
---
# Start
Read this first in every session. The harness judges each tool call; work passes only through an approved plan.

## The tools
| Tool | Use |
|---|---|
| `find(query, mode?)` | the skills and tool blocks that fit some words |
| `guide(name, mode)` | read a skill (`mode: "skills"`) or the actions of a block (`mode: "mcp"`) |
| `run(block, action, args)` | run one action |

With the MCP server they are `mcp__harness__find`, `mcp__harness__guide`, `mcp__harness__run`. Without it, the same
from the shell (`<core>` is the path the session-start message names):
```
python3 <core>/anchor.py cli tool find <words>
python3 <core>/anchor.py cli tool guide <name> --mode skills
python3 <core>/anchor.py cli tool run <block> <action> '<args as JSON>'
```

## The order of work
1. Understand the request: read the code, ask the user what is unclear. Reading needs no plan.
2. Plan: `guide("plan", "skills")`. Present the plan, ask the form, wait for the user's "Duyệt".
3. Build one step at a time: `guide("step", "skills")`. Edit, verify, `step_done`.
4. Ship when the user wants it pushed: `guide("ship", "skills")`.
5. Close: `guide("close", "skills")`.

## Always
- No edit before the user's "Duyệt" in the form. A typed "ok" approves nothing.
- Only the user answers a form: call AskUserQuestion with the questions alone, exactly as the harness gave them.
- Never `git commit` in the shell: `step_done` commits.
- Never open `.claude/state/`: read the ledger with `run("ledger", "db_query", {sql})`.
- Say in a shell call's description, in plain words, what the command does and what it changes.
- When a call is refused, read the reason, then `guide("refused", "skills")`. Never look for a way around a gate.

## The skills
| Skill | For |
|---|---|
| `plan` | writing, presenting and revising a plan |
| `step` | building a step: files, tests, verify, `step_done` |
| `ship` | commit, push, merge request, protected branches |
| `close` | closing a plan, settling old plans |
| `refused` | what each refusal means and the next move |
| `harness-map` | the harness's folders and limits (to change the harness) |
| `harness-rule` | adding a rule: translator, detector, rule row, test |
| `harness-action` | adding an action to a tool block |
| `harness-skill` | writing a skill |
| `harness-release` | tests, doctor, publishing, updating a session, the install |
