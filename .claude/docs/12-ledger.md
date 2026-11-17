# 12 - The ledger (what the harness records, by itself)

The ledger is the harness's one SQLite database, `state/harness.db` of the home. This document says how it is managed
and what every table holds, for this harness. It follows the general parts of the user's database spec (12); the
tables of blocks this harness does not have are not here.

The rule of this document: **the harness records, the model does not.** Every row below is written by the hook, the
tool server, a CLI door or the upkeep, never by a step the model has to remember.

## 1. How it is managed

### 1.1 Version and upgrade

- `utils/ledger/schema.sql` is a row of blocks, one per schema version (`-- version N` opens a block). A version only
  adds objects, so each version is the one before and more. A block is never changed once a release held it.
- The structure is pinned by a fingerprint: a hash over every table, index and view with its definition, spaces
  normalised. The structure decides the version; the file also keeps it in `user_version`.
- Version 1 is the structure copied from the real ledger (40 tables). Version 2 adds `pl_maint_runs`, `usage_daily`,
  `rolled_days` and `pl_plan_closures`. This is this harness's own version line, not the computer's.

| Ledger found | A writer |
|---|---|
| The latest version | opens and works |
| Exactly an older version's structure | is upgraded when the opener is the code in force; any other writer refuses with a hint |
| A newer version than the code | refuses: this code is not the release in force |
| Any other structure | refuses: it drifted |

- The upgrade (`utils/ledger/upgrade.py`) is one write transaction: check the old structure, create what is missing,
  set the version, check the new fingerprint, add one `pl_logs` row. Any fault rolls all of it back.
- The code in force is the published release of the home, or its work tree when none is published
  (`ledger_core.in_force`). Code that is not in force never upgrades a ledger.
- A read-only open (`ledger.db_query`, the doctor's chain check) does not check the structure.

### 1.2 Who writes, who reads

- Writers: the hook (every call), the tool server and the CLI door (every run of an action), the session start entry,
  the upkeep. Each takes the write lock for one short transaction.
- **A recording fault never blocks or changes a call.** It leaves one line on the error stream
  (`harness: not recorded in the ledger (...)`) and the call goes on (`assemble/engine/record_port.py`).
- **A guards-off grant lifts the checks, never the recording.** While it lasts the hook runs the harness as usual and
  only the verdict becomes allow (`contracts.waived`): prompts, calls, findings and the user's answers to forms are
  kept. A broken harness under a grant passes the call and says on stderr that it did not record.
- The model reads only through `run("ledger", "db_query", {sql})`: one SELECT, read only, at most 200 rows.
- The model writes only fixed shapes: a plan revision, a note, a judgment marked as its own (`ledger.annotate`).
  No gate takes authority from a row the model could have written.

### 1.3 What is never stored in clear

- A prompt, a shell line, a folder and an annotation's explanation pass `utils/ledger/mask.py`: a line with the shape
  of a secret (a private key, a cloud or forge token, an API key, a password in a URL) is stored as `[redacted]`.
- Long texts are cut: a prompt at 64 KB, a shell line at 4000 characters, an explanation at 300.
- A span of a tool call holds the names of its arguments, never their values.

### 1.4 Evidence and chains

Six tables are hash-chained: `rec_plans`, `rec_commits`, `pl_verify`, `pl_git_audit`, `pl_file_grants`,
`pl_behaviors`. Each row holds the hash of the row before it and its own. `run("ledger", "chain_check")` and the
doctor name the table and the first row where a chain breaks. A chain proves no row was changed, not that none is
missing at its end.

### 1.5 Upkeep

`utils/ledger/upkeep.py` runs after a commit (`step_done`) and at session start; it is once a day in effect.

1. **Roll up**: each finished UTC day with rows in `act_tool_calls`, `act_skill_loads` or `act_rule_decisions` that
   is not in `rolled_days` is counted into `usage_daily`, by the session's project and release. Today is not rolled.
2. **Prune**: rows older than 180 days leave `act_tool_calls`, `act_rule_decisions` and `pl_prompts`, only after a
   roll-up without error. Everything else is kept.
3. **Backup**: one copy a day (`VACUUM INTO`) in `state/backups/`, kept as the newest 7, the newest of each of the
   last 4 weeks (Monday first, UTC) and of the last 6 months.

A cloud machine is lost with its ledger: the copy that outlives it is the store on Google Drive
(`run("ledger", "export")`, skill `store`), which is separate from this daily backup.

## 2. The tables

Times are epoch milliseconds, UTC. "Kept" means never deleted.

### 2.1 Activity: what a session did

| Table | One row is | Written by | Life |
|---|---|---|---|
| `sessions` | One session: first and last time, epoch, project, release | The hook, when it first meets a session; `last_at` moves only at a prompt or a call of the harness's tools | Kept, one row per session |
| `pl_turns` | One turn: from a prompt to the end of the reply; `plan_id` is the first plan in force in it (0: none) | A prompt opens it, the first call with a plan links it, a Stop that may end closes it | Kept |
| `pl_prompts` | One prompt under its turn's number, masked, cut at 64 KB, marked when another session sent it | Each prompt | 180 days |
| `act_tool_calls` | One tool or shell event the harness judged, before it runs | Each `PreToolUse` | 180 days, then only its day total |
| `pl_spans` | One unit of activity: `gate` (a decision, ok or denied), `tool` (a run of a harness action, ok or error, argument names), `llm` (a reply of the model) | The hook, the `run` tool, the usage reader | Kept |
| `act_rule_decisions` | One finding of a call with the word Claude Code was given | Each call with findings | 180 days, then only its day total |
| `rec_edits` | One content this session gave a file: `wrote:<hash>:<path>`, counted | After each call that wrote a file, a shell line too when its targets can be read | Kept |
| `pl_maint_runs` | One shell line: a `start` row before it runs, then `ok`, `failed` or `interrupted` | Each shell call, before and after | Kept |
| `act_skill_loads` | One load of a skill, with its route (guide, tool, read, slash) and the session's epoch | The `guide` tool, and the hook for the other routes | Kept |
| `pl_usage` | The tokens of one message and token type (input, output, cache_write, cache_read) | At each end of a turn, from the new lines of the transcript; `ledger.usage_backfill` for older sessions | Kept |
| `pl_usage_offsets` | How far one transcript file is read | The usage reader | Kept, one row per file |
| `pl_session_meta` | The model and effort a session last ran with | The usage reader | Kept, one row per session |
| `pl_prices` | The list price of one token type of one model (USD per million tokens) | Seeded once into an empty table by `ledger.usage_backfill {write: true}` | Kept |
| `pl_annotations` | One judgment of the model about a span, a turn, a session or a plan | `ledger.annotate` (annotator always `LLM`) | Kept |

Notes:

- The epoch of a session rises by one when its context is compacted or cleared (the SessionStart hook's `source`).
  What a session knows now is what it loaded in its current epoch.
- A call of a harness action is recorded under `<block>.<action>`, by the hook (its gate span) and by the tool
  itself (its tool span).
- When the server judges a write from inside (its write gate, its commit or git line), that judging keeps its gate
  span and findings, with the calling session, and no second tool-call row: a call is counted once.
- Verify gives the tests no ledger: the ledger is always `state/harness.db` of the home that runs, so a test that
  records runs a copy of the tree (`copy_tree`), never the real home.
- Cost in the retro views is tokens times `pl_prices`: a conversion at list prices, not a bill. A model with no
  price costs 0 there.
- A prompt that is not the user's own words is marked (`from_peer` 1): a system notification (it starts with
  `<task-notification>`) or a peer's message. A live session showed that a peer's message arrives this way: the
  prompt is a notification, the message itself is in the answer of the `ReadNotifications` tool. There the harness
  keeps one `peer` span per message, with its sender and size, never its text. No gate reads the mark yet.
- `guide` and `find` calls are recorded as `guide.<name>` and `find`.

### 2.2 Plans and proof

| Table | One row is | Written by | Life |
|---|---|---|---|
| `pl_plan_revs` | One revision of a plan as presented: its items and the hash of its block | `plan_present`, `plan_revise` | Kept |
| `pl_plan_events` | One step in a plan's life: waiting, approved, executing, delivered, dropped | The desk, the approval, the steps, the close | Kept |
| `pl_plan_feedback` | What the user answered to a plan's form | The approval | Kept |
| `pl_approval` | The approval state of one session's desk | Present, approve, revise, close | One row per session |
| `rec_plans` | One plan number, given at approval (chained) | The approval | Kept |
| `pl_tickets` | One session's task: its plan in force, phase, step, commits | Every change of the task | Latest body per ticket, kept |
| `pl_behaviors` | One step in a behaviour's life: add, skip, retire (chained) | The approval, the doors, a skipped step | Kept |
| `pl_file_grants` | One file added to or dropped from a running plan (chained) | The `add file` and `add drop-file` doors | Kept |
| `pl_verify` | One verify receipt: command, result, content of each file (chained) | Each verify | Kept |
| `rec_commits` | One commit of a plan (chained) | `step_done`, `git.commit` | Kept |
| `pl_git_audit` | One git event the harness saw: a commit, a push (chained) | The git block | Kept |
| `pl_git_runs` | One failed git network try | The git block | Kept |
| `pl_plan_closures` | The closing of one plan's ticket: choice, facts, what does not match | The close form's answer, and the last step of a home plan | Kept |
| `pl_asks` | One one-use pass from the user's answer to a form | The form's answer; the action spends it | Kept |
| `pl_children` | One change of state of a child of a delegated plan | The orchestra actions | Kept |
| `pl_notes` | One version of a kept point; the guards-off grant too | The store records, the grant | Kept |
| `pl_logs` | One small event: gate-open, form, closure, a ledger upgrade | The desk, the close, the upgrade | Kept |

### 2.3 Roll-ups

| Table | One row is | Written by | Life |
|---|---|---|---|
| `usage_daily` | The total of one day, project, release, kind (tool, skill, rule) and name: calls, sessions, blocks | The upkeep | Kept for good |
| `rolled_days` | One UTC day already rolled | The upkeep | Kept |

### 2.4 Views

| View | Gives |
|---|---|
| `pl_plan_facts` | The newest revision of each desk plan, flattened for a review |
| `pl_retro_plan` | Per plan: revisions, time to approve, refusals, failed verifies, tokens, cost |
| `pl_retro_session` | Per session: turns, tool calls, errors, denials, model, effort, tokens, cost |
| `pl_retro_rule` | Per rule: how often it refused and what the session did next |

### 2.5 Tables nothing writes

These are part of the copied structure and stay empty here, because the block that would fill them is not in this
harness: `act_doc_reads` and `rec_plan_services` (no unit documents, no scope registering), `act_source_loads` and
`rec_plan_sources` (no tracker block), `pl_session_links` (no session links), `pl_plan_pages`, `pl_plan_extras`,
`pl_docs_state`, `pl_checks`, `pl_catalog`, `act_notes`. They are not to be built on.

## 3. What is not here, against the user's spec

| Part of the spec | Here |
|---|---|
| The transcript archive (`tx_` tables) | Not kept: it stores raw session content, which would go to the Drive store with every copy. It waits for the user's own decision. |
| One ledger for many machines | Each cloud machine has its own ledger; the Drive store holds whole copies, not joined. |
| Tables of the tracker, overlay, worktree and test-impact blocks | Those blocks are not in this harness. |
| `service` and `agent` columns of the activity tables | Written empty: a normal plan does not work in a unit yet, and the hook does not tell a subagent from its session. |
| Verify proofs in their own table | Kept inside the receipt. |

## 4. How to look

- What a session did: `SELECT tool, at FROM act_tool_calls WHERE sid = '...' ORDER BY at`.
- What was refused and why: `SELECT rule, tool, detail FROM act_rule_decisions WHERE verdict = 'deny' ORDER BY at DESC`.
- Shell lines that never reported: a `start` row of `pl_maint_runs` with no later row of the same command.
- Tokens and cost of a session: `SELECT * FROM pl_retro_session WHERE sid = '...'`.
- Whether the evidence is whole: `run("ledger", "chain_check")`.
- Usage of sessions from before this recording: `run("ledger", "usage_backfill")`, then with `{write: true}`.
