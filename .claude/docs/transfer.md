# Moving the old harness in

The old harness (`C:\AI-autonomous`) keeps running while its logic moves here. We carry the logic over, not the code:
each piece is rewritten to the rules of `architecture.md`. Each move is its own plan, and it lands only when the tests
and the doctor are clean.

## Done: the vertical slice
One flow runs end to end in its smallest form (`tests/e2e/test_flow.py`):

| Piece | Here | Still missing from the old harness |
|---|---|---|
| Ledger | the whole schema v5, fingerprint, one transaction a write, hash chains; the doctor compares the real ledger read only | the other tables' writers |
| Plan and approval | `plan_present` (a new plan, or a revision of a waiting one by `plan_id`), the form question, approval from the PostToolUse of AskUserQuestion, forged forms refused | feedback, plan pages, steps, children, scope of units |
| Edit gate | Write, Edit, MultiEdit, NotebookEdit and writes by the shell (Bash, PowerShell): approved plan, its files, never `state/`; real paths; a command it cannot read asks the user | MCP tools that write files |
| Verify | the unit's test command, a receipt of blob ids read before and after | test selection by impact, behaviours |
| Commit gate and delivery | a commit alone, in the plan's repository, verify passed, files unchanged since, plan files only; HEAD moved there: kept, delivered | multi-step plans, push, MR/PR |
| Pause | the user's form only, at most 120 minutes, traced first, works with a broken harness | — |

## Order of what is left
| # | What | Lands in |
|---|---|---|
| 1 | Done: the shell reader (`utils/shell_scan.py`, `utils/shell.py`, `gear/translate_place.py`); the commit gate reads git lines with it | — |
| 2 | Git guards: a command becomes a git action, with rules P1-P8 | `gear/translate_git.py`, `gear/git_cli.py`, `gear/rules/git.json` |
| 3 | Commit guards: secrets, AI marks, agent files | `gear/detect_secret.py`, `detect_mark.py`, `detect_agent.py` |
| 4 | Plans in full: steps, revisions, feedback, units and scope | `assemble/blocks.py`, `assemble/ports.py`, gears |
| 5 | Places and network: zones of a path, hosts of a command | `gear/zones.py`, `net_hosts.py`, `translate_net.py`, rules |
| 6 | The other blocks of the MCP server (session, notes, ledger reads...) | handlers in `assemble/`, the action table of `mcp/` |
| 7 | The skills | `skills/` |
| 8 | Wire this harness into a Claude Code session on a trial repository, then replay real sessions and compare verdicts | a plan of its own |

## Ledger
| Table | Written by |
|---|---|
| `pl_plan_revs`, `pl_plan_events` | `plan_present`, the approval, the delivery |
| `rec_plans` | the approval (chained) |
| `pl_verify` | `verify.run` (chained) |
| `rec_commits` | the delivery (chained) |
| `act_rule_decisions` | every call with findings |
| the other 34 tables | nobody yet: they wait for the tool that moves in |

The doctor compares the real ledger named in `project.json` with `schema.sql`, read only (`architecture.md`). When
the old harness changes its schema, the doctor names what drifted; `schema.sql` is then brought up to it by a plan.

## Known gaps of the slice
- A program the shell reader does not know (a script, `make`, `npm`) is asked of the user, who judges it by the
  agent's words; what it really writes is not seen. A program that only reads but is not in the tables is asked too.
- After `cd X` a relative path is read from both folders, so a pipeline (`cd X | rm y`) is judged on both.
- Whether Claude Code still shows its prompt for an ask in auto mode is proven only by row 8.
- Delivery takes the one commit made right on the approval's base; a plan of several commits waits for row 4.
- A commit made around the gate (a shell form the reader does not know, a name built at run time) can land in the
  repository; it is never delivered, but nothing undoes it.
- The hash chain does not see a row taken off its end (no anchor kept outside the DB yet).
- The edit gate sees Write, Edit, MultiEdit and NotebookEdit; MCP tools that write files are not seen yet.
- The form checks read questions and option labels; descriptions, previews and headers are left to the rule that
  each answer is found once in the response text.
- The commit reader refuses every git line it cannot read whole; merges, rebases, cherry-picks and aliases are
  refused until row 2 gives them their own rules.

## Into the home
When every row of the order is done and the replay is clean, `.claude/` of this repo replaces the old harness in
`C:\AI-autonomous`, through a plan of its own that the user approves. Unit `ai-harness` then leaves the home's
`project.json`, and `.claude/project/behaviors.json` (the old harness's record of the tests here) goes with it.
