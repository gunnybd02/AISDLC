---
name: harness-map
description: Develop the harness - the map of its folders (anchor, entry, hooks, gear, mcp, assemble, utils, nets, tests), what goes where, and the limits the doctor checks.
---
# Harness map
Read this before changing the harness itself. Python 3.13, standard library only, every `.py` file ASCII.

## When to use
- To find where a piece of harness code lives, or where a new one goes.

## The folders
```
anchor.py           the one file Claude Code runs; never written in a session
.mcp.json           the MCP server of this repository (calls the anchor)
.claude/
  settings.json     the hooks of this repository (call the anchor)
  project.json      the user's values: name, verify, protected, banned, ledger
  harness/
    entry/          the doors: hook, mcp_server, cli, doctor, install, session_start
    hooks/          hook JSON in and out, the answers of a form; decides nothing
    gear/           translate/ -> detect/ -> decide/arbiter.py, rule rows in rules/*.json
    mcp/            server/, tools/ (find, guide, run), actions/, skills/ (code), skill_docs/ (texts)
    assemble/       engine/ (connects the blocks) and pipelines/ (which gears run)
    utils/          shared code with no policy: contracts, ledger/, plan/, shell/, git/, gateway/, maint/
    nets/           the rules of the tree, run by the doctor
    tests/          tests/<block>/test_<module>.py, plus nets/ and e2e/
  entry/            three forwarders for machines set up before the anchor
  docs/             architecture.md and the specs; not part of a release
  state/            the ledger and the releases; closed to every tool
```

## The run of a call
Claude Code -> `anchor.py hook` -> `entry/hook.py` -> `assemble/engine/build.py` -> `hooks/io.py` (JSON to an event)
-> translators (facts) -> detectors (findings) -> `gear/decide/arbiter.py` (the verdict, from the rule rows) -> the
answer to Claude Code. A broken harness exits 2, which blocks the call.

## What goes where
| To add | Read |
|---|---|
| a rule on tool calls | `guide("harness-rule", "skills")` |
| an action the model can run | `guide("harness-action", "skills")` |
| a text for the model | `guide("harness-skill", "skills")` |
| a shell door for the user | `assemble/engine/cli_wire.py` and its `cli_*.py` files |
| code two blocks share | `utils/`, with no policy in it |

## The limits (the nets)
| Net | Rule |
|---|---|
| `layout` | a file is only where `harness/nets/layout.json` allows |
| `imports` | `hooks`, `gear`, `mcp` import only themselves and `utils`; `utils` imports no block; `assemble` connects; `entry` imports only `assemble`, inside `main()` |
| `size` | a `.py` file has at most 400 lines, a `.md` file at most 300 |
| `verdict` | the verdict words and `Verdict` appear only in `gear/decide/arbiter.py` and `utils/contracts.py` |
| `config` | `project.json` is named only in `assemble/engine/config.py` |
| `bridges` | no file only passes names on |
| `entry` | an entry script imports only the standard library at load time, and its `main()` catches everything |

## Check the work
From `.claude/`: `python3 -m unittest discover -s . -t .` and `python3 harness/entry/doctor.py`, both clean. Or
`run("health", "doctor", {})` and `run("health", "items", {})`. More: `.claude/docs/architecture.md`.
Then `guide("harness-release", "skills")`: a change runs nowhere until it is published.
