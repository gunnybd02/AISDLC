---
name: harness-release
description: Develop the harness - test it, run the doctor, publish a release, update a running session to the newest main, and how the install puts it on a machine.
---
# Harness release
A session never runs the files it edits. It runs a release: a copy of `harness/` under `state/live/<sha>/`.

## When to use
- After a change to the harness, to make it run; and to bring a session to a newer harness.

## Steps
1. From `.claude/`: `python3 -m unittest discover -s . -t .` passes.
2. `python3 harness/entry/doctor.py` says `0 errors`.
3. Commit through the plan (`guide("step", "skills")`), push the branch, open the pull or merge request.
4. After the merge to main, each session takes it in one of two ways:
   - A new session: its start brings the harness to the newest main by itself, when the doctor is clean.
   - A running session: `python3 <core>/anchor.py cli live update`. It asks the form
     `Cho phép phát hành harness <sha>?`; after the user's "Cho phép", run it again. No restart.
5. To run the work tree's own code before a merge (a PC, the core's own repository):
   `python3 <core>/anchor.py cli live publish`, the same form, then again.
6. `python3 <core>/anchor.py cli live status` says which release is in force.

## What takes effect when
| Changed | Runs after |
|---|---|
| gear, hooks, rules, skills, actions | the next hook call or tool request after the release is in force |
| `anchor.py`, `.claude/settings.json`, `.mcp.json` | a new session (Claude Code reads them at its start) |
| the install (hooks of the user, permission rules) | `python3 <core>/.claude/harness/entry/install.py` again |

## The install
- A PC: Claude Code is started in the core repository; its `.claude/settings.json` and `.mcp.json` switch the
  harness on.
- A machine for every session (the cloud): `python3 <core>/.claude/harness/entry/install.py` writes the hooks into
  the user's settings, registers the MCP server and allows the harness's own CLI. `--uninstall` takes it out.
- One core: when a harness is installed for the user, a repository's own copy gives way to it. Never two harnesses.

## Notes
- A release whose doctor fails is never put in force; the session keeps what it runs.
- A session never runs the session start itself, and never writes the anchor or the wiring files.
- `docs/` is not part of a release: a doc fix needs no publishing.
