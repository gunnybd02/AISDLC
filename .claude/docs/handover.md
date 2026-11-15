# Handover: where the harness stands, and what comes next

Written at the end of a long session (it ran out of machine time) for the session that continues the work. A new
session cannot read the old chat; it reads this file. Details not here are in `docs/architecture.md`,
`docs/live-test.md`, `docs/migration-map.md`, and, slowly, in the old chat (session `session_01EXL6xY5uGx26YMuQyXbhjh`).

## The model the user works by

- One **core**: a `.claude/` folder with the harness (this repository), its config and its one ledger
  (`state/harness.db`). Every session runs under it.
- The repositories a session works on (repoA, repoB...) are outside the core and never hold a harness of their own.
- On a PC, Claude Code is started in the core repository: its `.claude/settings.json` and `.mcp.json` switch the harness
  on. In the cloud, the environment's setup script installs the core at `~/.harness`; nobody clones it by hand.
- Never two harnesses, never two ledgers. A copy that is not the core gives way (`anchor.py`, `--project`).

## How the user wants the work done

- Explain simply and briefly; when asked "simpler", shorten again. English, with the form labels in Vietnamese.
- Before building: present the plan in a form (AskUserQuestion) with the question
  `Duyệt plan "<title>" (<pd-id> rev N)?` and the options "Duyệt", "Sửa plan", "Bỏ plan". Build only after "Duyệt".
- After building: tests and doctor, a pull request, then ask in a form "Merge PR #N?" ("Cho phép" / "Không") and
  merge it yourself on "Cho phép" (merging through the GitHub API works from a cloud session).
- Test live in a real cloud session when a change touches how sessions start; say plainly what was not tested.
- Never ask for a token or a secret in chat. No force push. All `.py` files are ASCII (Vietnamese as `\u` escapes).

## What is built (all merged to main)

| PR | What it gave |
|---|---|
| #1, #2 | The block folders (`gear`, `hooks`, `mcp`, `assemble`, `utils`), one store, the plan lifecycle of spec 04 (ticket, desk, form, steps, files gate, verify, `step_done`, closing), commit guards, git rules P1-P8 (protected branches only, ask, kept in SQL), shipping (`git.commit`, `git.push`, MR form), releases (`boot.py` runs `state/live/<sha>`, `live publish` with "Cho phép") |
| #5 | `entry/install.py`: hooks and MCP server in the user's settings, so every session of a machine is governed |
| #6 | `boot.py cli tool find\|guide\|run`: the MCP tools from the shell, for a session that has none |
| #7 | `cli live update`: a running session takes the newest main after "Cho phép", no restart |
| #8 | The install allows the harness's own CLI in the user's permissions (auto mode blocked it) |
| #9 | SessionStart hook: a session starts on the newest main when its doctor is clean |
| #10 | The session-start message says how to reach the tools without the MCP server |
| #11 | One core: the repository's own wiring is back and gives way to an installed core |

361 tests pass (1 skipped, Windows only); doctor: 0 errors.

## The cloud, as it runs now

- The user's Default environment has a setup script: clone this repository to `~/.harness`, run
  `.claude/harness/entry/install.py`. Every new cloud session is governed without selecting this repository.
- Cloud machines are prepared ahead of time. The SessionStart hook brings the harness to the newest main when the
  session begins. Changing the setup script (even a comment) makes the cloud prepare fresh machines.
- The MCP tools load reliably only from a repository's `.mcp.json` (the cloud's supported way). A session on this
  repository has them; a session on another repository may not, and then uses `anchor.py cli tool ...`.
- Checked live: install, refusal before a plan, update at start, MCP and shell tools, presenting a plan, one core with
  this repository cloned. **Not checked live:** the flow after a real "Duyệt" click (edit, verify, `step_done`,
  delivered); test sessions run alone and cannot answer a form. The first governed session with the user does it.

## Facts found, worth keeping

- A cloud session's machine is temporary: its ledger is lost when the session idles long, is archived or deleted, or
  runs out of time (this one did after two days). Only what is pushed to GitHub survives. Ledger sync across sessions
  is postponed by the user's decision.
- `claude --bg` (spec 05's way to start a child) fails in the cloud: "Workspace not trusted", and nobody can click the
  trust prompt. `claude agents --json` works; headless `claude -p` starts without the prompt.
- Subagents (the Agent tool) run in the parent's session, but every hook payload of a subagent's tool call carries
  `agent_id` and `agent_type`, and there are SubagentStart / SubagentStop events: the harness can tell children apart.
- A cloud session can open other cloud sessions with a tool (`create_session`), each on its own machine with its own
  ledger; the harness code cannot start them itself.
- This cloud connection cannot delete branches on GitHub (403); merging and pushing work.

## What comes next, in this order

1. **A real governed run with the user**: done on 2026-11-15 (the "Duyệt" click, edit, gate refusals). It fixed
   verify on a plan without tests and wrote `docs/05b-orchestra-cloud.md`; what it left open is item 5.
2. **Spec "05b - Orchestra in the cloud"** (a document first, for the user's review). The user's spec 05 (delegated
   plans with children) assumes one machine: shared ledger, worktrees, `claude --bg`. The cloud extension the user
   asked for: children as separate cloud sessions. The card travels in the brief; the child works on its own branch
   and pushes it; the handback comes back as a message; the parent fetches the branch, runs the AC tests, merges.
   Nothing important stays only in a child's ledger. Children as subagents on the parent's machine are the second
   option (close to spec 05, one ledger). Spec 05 itself is saved as the user pasted it: `docs/05-orchestra.md` (sections 1-7) and
   `docs/05-orchestra-2.md` (sections 8-12).
3. **Orchestra, spec 05, for the PC**: not built. Today: `children` is a plan item the desk accepts and prints, the
   `pl_children` table exists (without the `why` and `checks` columns), the verify lock is worktree-aware. Missing:
   units in the config, worktrees (`utils/worktree`), the card (`utils/plan/children.py`), the crew and the rest of
   `utils/orchestra/`, the sessions port, the actions, `orchestra watch`, the skill. Order: units, worktrees, card and
   delegated opening, crew (spawn, take, handback), check and accept, watch, reach and cleanup, lineage.
4. Smaller items: the start message is written by the version that ran before the update (let the new version write
   it); the wiring files use `python3` (a Windows PC with only `python` needs that word changed; never tested on
   Windows, nor against the user's real ledger); a real GitLab merge request was never opened; `ports.py` is near the
   400-line cap; the notes block and the gitlab read actions are not built.
5. Found by the first governed run (2026-11-15), not fixed: (a) the harness's `verify` fails 24 tests in its own
   environment (the MCP server's; one of them fails as soon as `CLAUDE_PROJECT_DIR` is set) while the same command
   passes 364 by hand, so `step_done` cannot commit a change to this repository; that run was committed with the guards
   off. (b) Running the unit tests by hand in a governed shell leaves a test plan in the live ledger (session `flow`,
   root under `/tmp/harness-test-*`), and `cli verify` then picks that plan. (c) The shell-write gate reads a
   relative path from the session's kept folder, not from the `cd` in the command. (d) An approved plan cannot have a
   file path corrected: `add file` needs a behaviour, so a docs plan needs a new plan and a new approval.
6. For the user to do: delete the merged branches on GitHub (`harness/*`, `install/user-level`,
   `refactor/block-folders`, `wire/harness-session`, `test/mcp-json`).
