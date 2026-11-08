# Moving the old harness in

The old harness (`C:\AI-autonomous`) keeps running while its logic moves here. We carry the logic over, not the code:
each piece is rewritten to the rules of `architecture.md`. Each move is its own plan, and it lands only when the tests
and the doctor are clean.

## Order
| # | What | Lands in |
|---|---|---|
| 1 | The shell reader (split, quotes, heredoc; unwrap `sh -c`, `eval`, `xargs`), git runs and facts, the staged diff | `utils/` |
| 2 | Git guards: a command becomes a git action, with rules P1-P8 | `gear/translate_git.py`, `gear/git_cli.py`, `gear/rules/git.json` |
| 3 | Commit guards: secrets, AI marks, agent files | `gear/detect_secret.py`, `detect_mark.py`, `detect_agent.py` |
| 4 | Places and network: zones of a path, hosts of a command | `gear/translate_place.py`, `translate_net.py`, `zones.py`, `net_hosts.py`, rules |
| 5 | The ledger: the full schema v5, one transaction per write | `utils/ledger/` |
| 6 | The blocks of the MCP server (plan, session, notes...) | handlers in `assemble/`, the action table of `mcp/` |
| 7 | The skills | `skills/` |
| 8 | Replay real sessions through the new hook, compare verdicts, then replace the old harness | a plan of its own |

Ports (the facts a translator or a detector reads from outside, such as git or files) are built in `assemble/ports.py`
when the first one is needed.

## Ledger
The schema is copied whole, so a tool that moves in finds its table ready. Two checks guard it:
- **Pinned:** opening the private DB compares its fingerprint with `schema.sql`.
- **Against the real ledger:** the doctor opens the real ledger read only (`mode=ro`) and compares the schema
  fingerprint. If it cannot open it (WAL without `-shm`), it says so, and never takes that as a match.

The fingerprint covers tables, columns, constraints, indexes, triggers and view bodies, with spaces and comments
normalised.

| Table | Written by |
|---|---|
| (none yet) | the ledger has not moved in |

## Into the home
When every row of the order is done and the replay is clean, `.claude/` of this repo replaces the old harness in
`C:\AI-autonomous`, through a plan of its own that the user approves. Unit `ai-harness` then leaves the home's
`project.json`, and `.claude/project/behaviors.json` (the old harness's record of the tests here) goes with it.
