# Handover: where the harness stands, and what comes next

Written at the end of a long session (it ran out of machine time) for the session that continues the work. A new
session cannot read the old chat; it reads this file. The frame of every plan is `docs/map.md`. Details not here are in `docs/architecture.md`,
`docs/live-test.md`, `docs/migration-map.md`, and, slowly, in the old chat (session `session_01EXL6xY5uGx26YMuQyXbhjh`).

## The model the user works by

- One **core**: a `.claude/` folder with the harness (this repository), its config and its one ledger
  (`state/harness.db`). Every session runs under it.
- The repositories a session works on (repoA, repoB...) are outside the core and never hold a harness of their own.
- On a PC, Claude Code is started in the core repository: its `.claude/settings.json` and `.mcp.json` switch the harness
  on. In the cloud, the environment's setup script installs the core at `~/.harness`; nobody clones it by hand.
- Never two harnesses, never two ledgers. A copy that is not the core gives way (`anchor.py`, `--project`).

## How the user wants the work done

- Explain simply and briefly; when asked "simpler", shorten again. English only, the form labels too.
- Before building: present the plan in a form (AskUserQuestion) with the question
  `Approve plan "<title>" (<pd-id> rev N)?` and the options "Approve", "Change plan", exactly as `plan_present` prints
  it, after presenting the plan through the harness. Build only after "Approve".
- After building: tests and doctor, a pull request, then ask in a form "Merge PR #N?" ("Allow" / "Deny") and
  merge it yourself on "Allow" (merging through the GitHub API works from a cloud session).
- Test live in a real cloud session when a change touches how sessions start; say plainly what was not tested.
- Never ask for a token or a secret in chat. No force push. All `.py` files are ASCII (Vietnamese as `\u` escapes).

## What is built (all merged to main)

| PR | What it gave |
|---|---|
| #1, #2 | The block folders (`gear`, `hooks`, `mcp`, `assemble`, `utils`), one store, the plan lifecycle of spec 04 (ticket, desk, form, steps, files gate, verify, `step_done`, closing), commit guards, git rules P1-P8 (protected branches only, ask, kept in SQL), shipping (`git.commit`, `git.push`, MR form), releases (`boot.py` runs `state/live/<sha>`, `live publish` with "Allow") |
| #5 | `entry/install.py`: hooks and MCP server in the user's settings, so every session of a machine is governed |
| #6 | `boot.py cli tool find\|guide\|run`: the MCP tools from the shell, for a session that has none |
| #7 | `cli live update`: a running session takes the newest main after "Allow", no restart |
| #8 | The install allows the harness's own CLI in the user's permissions (auto mode blocked it) |
| #9 | SessionStart hook: a session starts on the newest main when its doctor is clean |
| #10 | The session-start message says how to reach the tools without the MCP server |
| #11 | One core: the repository's own wiring is back and gives way to an installed core |
| #15 | `anchor.py` at the repository root is the one file Claude Code runs; the doors are in `harness/entry/` (the three forwarders it kept in `.claude/entry/` were removed in #43) |
| #16 | The skill texts are in `harness/mcp/skill_docs/<name>/SKILL.md`, part of a release (a changed skill needs "Allow") |
| #17 | `nets/` and `tests/` are inside `harness/` |
| #18 | The first real skills: `start`, `plan`, `step`, `ship`, `close`, `refused` (working under the harness) and `harness-map`, `harness-rule`, `harness-action`, `harness-skill`, `harness-release` (developing it); the session-start message points to `start`; the doctor refuses a skill that names an action, block or skill that is not there |
| #19 | The skills are whole workflows, three files: `work` (any repository: gather context, plan, build, ship, close), `harness-dev` (the harness itself: gather context, plan, build, check, pull request, release) and `refused` (the lookup of every refusal); the session-start message points to `work` |
| #20 | The release a session start puts in force writes the start message's hint (`cli live hint`): a machine prepared with older code no longer names a skill the new release lacks |
| #21 | The ledger store on Google Drive: `run("ledger", "export")` copies the whole ledger (schema checked, named by session, time, commit and schema) and says the one Drive `create_file` call that uploads it; a commit's answer says the copy is due; the skill `store`; trashing, moving or renaming a Drive file asks the user (`drive.remove`, `drive.move`). The folder id is the environment variable `HARNESS_DRIVE_FOLDER`, never in the tree (the repository is public) |
| #22 | The ledger's copy goes to `.harness-export/` of the session's working folder (git ignores it): the Drive tool reads a file by reference only from a session's own folders, a temp folder is refused (found by the live check of #21) |
| #23 | The store's lifecycle (`utils/ledger/store.py`, rows of `pl_notes`): a copy has a record inside the ledger and a name that say ledger, number, session, reason, time and commit; a copy is due at a checkpoint (after a push or merge request, when a plan closes, or when the end of a turn is held: `store.unsaved`, once for the same work), no longer after each commit; the hook keeps that the store holds a copy when the Drive tool answers with its file; `run("ledger", "store_status")`. Also mends `git.commit`, whose answer failed after the commit was made (a name not imported, from #21) |
| #24 | A Drive call is known by what it is, not by its server's name: a cloud session can name a connector's tools by an id (`mcp__caaed075-...__create_file`), so the upload was not kept and the Drive guard did not see a trash or a move (found by the live check of #23) |
| #25 | Every function says what it takes and gives: type hints on all 555 functions, docstrings with Args, Returns and Raises; the data named in `utils/shapes.py` (`ApprovedPlan`, `Ticket`, `Receipt`, `PlanStore`...); the `hints` net keeps it. Files split to stay under 400 lines: `ports.py` (LedgerCore, DeskPort, TicketPort), `desk.py` (`item_checks.py`), `place_ops.py` (`write_ops.py`, `cmdlets.py`), `scan.py` (`command.py`, `dialects.py`) |
| #26 | Orchestra, part 1 (`docs/05b-orchestra-cloud.md`): the user's full spec 05 saved in four files; the card rules of spec 5.1 (`utils/orchestra/card.py`; several children may share a unit in the cloud); a plan with children opens a delegated ticket (grant, crew, a pending row per child) and no other plan opens beside it; block `orchestra`: `spawn` (the brief and the `create_session` call), `started`, `status`; `git ls-remote` is read-only |
| #27 | The shell reader knows `git ls-remote` reads only (found by the live check of #26) |
| #28 | Orchestra, part 2: a brief as a session's first prompt makes it a child; `take` opens its card plan by the parent's grant (no form) on `orch/p<plan>/<name>`; `push`, `question`, `handback` (the receipt `.harness/handback/<name>.json` committed and pushed); a child never asks the user, presents or closes a plan, asks for the maint grant, merges or pushes another branch (`child_guard`) |
| #29 | A project's tests never see the harness in force: `verify` and the test package drop `HARNESS_HOME`, `HARNESS_CODE`, `HARNESS_SESSION` (and the tests `CLAUDE_PROJECT_DIR`); before, the harness's own suite failed 22 tests in a governed session and wrote test plans into the live ledger (found by orchestra's live run with one child) |
| #31 | Units in `project.json` (`repo`, `path`, `verify`, `base`: any repository, or a folder of a shared one); orchestra gives a child its unit (clone, folder, test command, PR target); fixes from the live run: a child is never asked (the arbiter turns a question into a refusal with "go on", `child.no_keyboard`), its card plan waits for its handback, it keeps its role on a new ticket, the brief says to verify from the shell |
| #32 | Orchestra, part 3, the parent: `check` (the receipt on the child's branch, the AC behaviours, the tests rerun by the parent), `accept` (one pull request into the unit's base, through `gh api`), `reject` (3 rounds), `answer`, `forget`, `read`, and `land`, the final route (merge every pull request, a conflict stops it for the parent to resolve or reject, each unit's tests on the merged base, the plan closes delivered) |
| #34 | Orchestra, part 4: `release`, `remove` (one checklist the user ticks, then the `archive_session` calls), `digest`; the check-in for a child that dies silently; receipts kept out of the base (accept takes the file off the branch, the ledger keeps it); the skill `orchestrate`; the test leftovers `orch-probe/` and `.harness/handback/` removed from main |
| #37 | Orchestra fixes from the two-child live run: `accept` takes the receipt off the child's branch with a git commit and a branch push (the cloud's proxy refuses GitHub's file API); `take` starts a child's branch from its unit's base |
| #38 | A delegated plan is done only when every child's database is in the Drive store: copies carry the plan marker `orch.<plan id>.<child or parent>`; a child uploads at handback; the hook reads Drive's own search answer to verify each child's copy; `land` delivers and `remove` archives only verified children (a dead child only with the user's Allow) |
| #40 | From the live run of #38: a child's copy in Drive is recognised by its own harness id, which its receipt names (it differs from its cloud session id); `land` waits for GitHub's mergeability and does not call a refusal with a clean local merge a conflict; the Drive search is given in Drive's own query syntax |
| #42 | The remove checklist always has two choices: a question of one child also offers "Keep all", which archives nothing and wins over ticks (the form tool refuses a question with one option: found live) |
| #43 | The `## Plan` block follows the plan spec (04, sections 7.3, 8, 10): a bare heading, one line per item, overview and code first for a plan with code, the whole card on a child's line (so its criteria are shown and hashed), no Root line; `plan_present` answers the spec's head line, `plan_revise` only the changed lines. One entry folder: the forwarders of `.claude/entry/` are gone; a machine whose hooks still name `.claude/entry/boot.py` runs `python3 .claude/harness/entry/install.py` once |
| #44 | The ledger records every action by itself (`docs/12-ledger.md`): a schema version with one upgrade door (only the code in force upgrades); turns, prompts, tool calls, gate and tool spans; file writes and shell lines; skill loads, the session's epoch, project and release; tokens and cost from the transcript; upkeep (daily totals, pruning at 180 days, a daily backup); a closure row; `ledger.chain_check`, `ledger.annotate`, `ledger.usage_backfill`. A recording fault never blocks a call. A step no longer owes the tests of later steps |
| #45 | The plan cycle as spec 04 says (a new plan replaces the waiting one, a revision shows only what changed, card files counted, replaced test items drop old behaviours, a staged deletion commits); the recording tells the user from others (notifications and peer messages, `peer` spans), names guide and find, counts what the backfill writes; verify makes no ledger copy; `docs/map.md`, the map of the brain |
| #46 | A child's brief sends it to the ledger door (`ledger.db_query`), never the ledger file. (Its `send_message` allow rule did nothing and is gone again in #47.) |
| #47 | Parent and child talk through git, never by message (`05b-orchestra-cloud.md` 2b): a cloud child cannot message its parent (live checks 2026-11-17). A question and the receipt are pushed on the child's branch and the child stops; `reject` and `answer` push a note there and `spawn` opens a fresh session that reads it, its rounds kept. The `peer` span reads the notifications answer's strings, not its JSON text |
| #49 | Leftovers of talking through git: `started` points to `check`; the store step sends no message; `check` shows a question a child pushed |
| #50 | One owner per concept (`13-cloud-foundation.md`): `now`, `session_of`, `answered`, `ProblemsError` in contracts; one reader of the plan in force; the **owners net** (copied bodies, `ports.get` in actions, `run(...)` naming no action); orchestra `limits` {children, rounds} in `project.json` |
| #51 | Spec 13 gaps closed: a broken harness blocks only a tool call; a gear fault is a verdict (`gear.fault`, `gear.fault_after`); the english net; the imports net refuses third-party packages, code from text, `sys.path` use and unnamed entry imports; fitness tests for a new detector (4 files) and a new action (1 file) |
| #52 | Pipelines stand alone (spec 13 section 7): `extends` is refused, the engine puts the floor under a plan's pipeline, the doctor reads every pipeline file and names unknown gears |
| #53 | A unit's pipeline comes from the config (spec 13 section 11.6): `units.<name>.pipeline` in `project.json`; a plan runs the floor plus the pipelines of its services; the doctor names a unit whose pipeline has no file |
| #54 | When rows (spec 13 section 7): a row `code, verdict, why, when, test` matches the facts of rule actions; translators declare their vocabulary (READS for the port facts they read); the git rules are when rows, `gear/detect/git.py` gone, every git verdict and message kept; a stricter row (a force push anywhere) needs no Python |
| #55 | Every command check is a when row: commit, the server's write actions, Drive, agent files, the child and the plan files describe in `gear/translate/` and their rows decide; every rule action names its kind; an action that must be judged and meets no row is asked (`rule.unmatched`); only the content and state detectors remain |
| #57 | Publish on merge, with a fallback: `live update` puts merged main in force with no form (the merge was the user's word; files not tracked under `harness/` stop it); after a merge tool merges the harness's own repository, the hook does the update by itself. Each publish keeps `state/live/previous`. `anchor.py` holds the fallback: a release whose hook crashes twice is left for the previous one and listed in `state/live/bad` (no update puts it back); the anchor's own MCP server `fallback` (`rollback`, `status`, in `.mcp.json` and the install) never loads a release, and the hook lets its calls pass, so a release that refuses everything can still be rolled back. One step back only |
| #58 | A guards-off grant lifts the checks, never the recording: the hook runs the harness under a grant with the verdict waived (`contracts.waived`), so prompts, calls and form answers (an "Approve") are kept; a broken harness still passes. Each turn names the first plan in force in it (`pl_turns.plan_id`) |
| #61 | Repositories by URL (`system.md`): a plan names its repos ({url, base, verify, path, pipeline}), limits and banned words, all shown in form 1; a plan with repos is kept only from a clone of one and takes its test command; protected branches come from GitHub (`utils/forge/protection.py`, kept 10 minutes, never fewer than main and master, plus the plan's bases); `config.py`, the config net and every reader of `project.json` are gone; the doctor reads `HARNESS_LEDGER`; a ready line per repo in the plan block. The file `project.json` stays until a release without readers is in force, then a small plan deletes it |

About 565 tests pass (1 skipped, Windows only); doctor: 0 errors.

Learned in #61: the release in force runs its own copy of `harness/`, but reads the other files of the home (such as
`project.json`) from the home's working tree. Deleting one there broke the live harness at once; the fallback could
not help, since the previous release read the same file. A grant (the form still works on a broken harness) restored
it. Never remove a home file a release in force still reads.

Learned in #57: a guards-off grant made the hook pass everything without recording, so an "Approve" given while the
guards were off was lost (fixed in #58). And harness work is done in the home clone (`~/.harness` in the cloud): from
another clone of this repository, `step_done` refuses `.claude/` files as a unit's agent files.

## The cloud, as it runs now

- The user's Default environment has a setup script: clone this repository to `~/.harness`, run
  `.claude/harness/entry/install.py`. Every new cloud session is governed without selecting this repository.
- Cloud machines are prepared ahead of time. The SessionStart hook brings the harness to the newest main when the
  session begins. Changing the setup script (even a comment) makes the cloud prepare fresh machines.
- The MCP tools load reliably only from a repository's `.mcp.json` (the cloud's supported way). A session on this
  repository has them; a session on another repository may not, and then uses `anchor.py cli tool ...`.
- Checked live: install, refusal before a plan, update at start, MCP and shell tools, presenting a plan, one core with
  this repository cloned. **Not checked live:** the flow after a real "Approve" click (edit, verify, `step_done`,
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

## The folder layout the user asked for

`anchor.py` at the root, and everything that runs in one folder, `.claude/harness/`: `entry/`, `gear/`, `hooks/`,
`mcp/` (code in `skills/`, texts in `skill_docs/`), `assemble/`, `utils/`. Done: the anchor and `entry/` (#15), the
skill texts (#16), `nets/` and `tests/` (now `harness/nets/`, `harness/tests/`; a rule row names its test as
`harness/tests/<block>/test_x.py#test_y`). A release is the `harness/` folder.
`docs/` stays outside (a doc fix must not be a new release). Run the tests from `.claude/`:
`python3 -m unittest discover -s . -t .`, and the doctor: `python3 harness/entry/doctor.py`.

## What comes next, in this order

1. **A real governed run with the user**: done on 2026-11-15 (the "Approve" click, edit, gate refusals). It fixed
   verify on a plan without tests and wrote `docs/05b-orchestra-cloud.md`; what it left open is item 5.
2. **Orchestra in the cloud** (`docs/05b-orchestra-cloud.md`, decided by the user on 2026-11-16: children are cloud
   sessions, the card rides in the brief and the receipt on the child's branch, at most 3 run). A live probe showed a
   child acts on a parent's note only because its brief says so; parent and child talk only through the child's branch (#47). All four parts are built (#26, #28, #31, #32, #34),
   live-tested one child at a time; a run with several children at once is next.
3. **Spec 05 for the PC** (`docs/05-orchestra.md` to `05-orchestra-4.md`, worktrees and `claude --bg`): set aside for
   the cloud path the user chose; its card, crew, check and accept rules are the ones the cloud parts follow.
4. Skills: the three of #19 were written from this code. The user's own skills (their old harness on the PC, such
   as `orchestrate`) were never in this repository; they go beside these when the user pushes or pastes them. Two
   rule rows still name the old command (`stop.unverified` and `agent.registry` say `python3 -m entry.cli ...`; it is
   `python3 <core>/anchor.py cli ...`, as the `refused` skill says).
   Smaller items: the wiring files use `python3` (a Windows PC with only `python` needs that word changed; never tested on
   Windows, nor against the user's real ledger); a real GitLab merge request was never opened; `ports.py` is near the
   400-line cap; the notes block and the gitlab read actions are not built.
5. Found by the first governed run (2026-11-15). (a) and (b) are fixed by #29: the harness's `verify` failed 22
   tests in its own environment and the tests wrote to the live ledger, because `HARNESS_HOME`, `HARNESS_CODE` and
   `HARNESS_SESSION` reached them (an orchestra child's verify met it again on 2026-11-16); `verify` and the test package
   now drop them. Not fixed: (c) The shell-write gate reads a
   relative path from the session's kept folder, not from the `cd` in the command. (d) An approved plan cannot have a
   file path corrected: `add file` needs a behaviour, so a docs plan needs a new plan and a new approval.
6. For the user to do: delete the merged branches on GitHub (`harness/*`, `install/user-level`,
   `refactor/block-folders`, `wire/harness-session`, `test/mcp-json`).
