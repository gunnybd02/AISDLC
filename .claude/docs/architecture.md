# Architecture of the harness

Everything lives under `.claude/`. Python 3.13, standard library only.

```
.claude/
  entry/        hook.py, mcp_server.py, doctor.py: what Claude Code runs; they call only assemble/engine
  harness/
    hooks/      hook JSON in and out (io.py), the answers of a form (forms.py); decides nothing
    gear/       translate/ -> detect/ -> decide/arbiter.py, with the rule rows in rules/*.json
    mcp/        what the model calls: server/ (stdio, tool base), tools/ (find, guide, run), skills/ (library),
                actions/ (one file per block of actions, ACTIONS = [...])
    assemble/   engine/ (loader, config, ports, runner, select, pipeline, build, wire_mcp, checks) and pipelines/
    utils/      shared code with no policy: contracts, ledger/, plan/, shell/, git/
  nets/         the rules of the tree, checked by the doctor
  project.json  the values of the user (name, verify: the unit's test command, ledger: the real ledger)
  project/skills/  the skill library, served by find and guide
  docs/         this file, transfer.md, migration-map.md
  tests/        tests/<block>/test_<module>.py, plus nets/ and e2e/
  state/        private, not in git: harness.db, the ledger, the one store of the harness's data
```

## The flow of a change
```
run("plan", "plan_present", {plan})      the plan is data (utils/plan/desk.py: clean, normalize, check; tier light
                                         or full); the revision waits in the ledger with the session that presented
                                         it; the answer is the ## Plan block (render.py) and the form call
                                         Duyệt plan "<title>" (<pd-id> rev N)?; plan_revise keeps rev+1 with only
                                         the given items, plan_drop stops a waiting plan, plan_show and plan_status
                                         read one
AskUserQuestion                          the user answers; only "Duyệt" to that exact question approves it
                                         (a bare ok / duyệt / đồng ý typed in the chat approves nothing: FORM_ONLY);
                                         the approval opens the plan in one transaction (utils/plan/opening.py):
                                         rec_plans, pl_behaviors with tests, the ticket, pl_approval, the events
                                         approved and executing, pl_logs gate-open and form
Write / Edit, or a write by the shell     allowed only for the files of the approved plan (detect/tracked.py, detect/planfiles.py)
python3 -m entry.cli verify [--in F] [--timeout S] [-- cmd]  (or run("verify", "run", {plan})): the test command
                                         (after --, else the config's verify) of the session's plan, no shell, under
                                         a lock in the git common dir (shared with worktrees), with HARNESS_DB set to
                                         a copy of the live ledger; exit 124 on the timeout (600 s, 1..3600), 127 when
                                         it cannot start; the receipt keeps each file's blob id read before and after
                                         the tests (a file that changed under them: no pass). The doors add file,
                                         add test, add drop-file, add retire-test and behaviors add|list|check|retire
                                         widen or shrink the plan with chained pl_file_grants and pl_behaviors rows
run("plan", "step_done", {message})      the current step of the session's plan (utils/plan/steps.py): refused
                                         with no message, nothing changed, a file of another step, what the step
                                         owes (its behaviours' tests, a green verify of the current files), a
                                         protected branch or a secret; else the harness commits the step's changed
                                         files, the next step opens, and after the last a home plan closes
                                         delivered (no form). step_skip {why} gives a step up; a write to a plan
                                         file in deliver goes back to execute, and the next step_done is a fix
run("git", "commit", {files, message})   named files of the plan (never ., a folder or outside it): refused on a
                                         protected branch, with no plan, a file the plan does not allow, a code file
                                         no green verify saw, or a commit guard; the step does not move: step_done
                                         adopts the commit once proven
run("git", "push")                       a unit plan's branch in deliver only (a home plan closes itself after its
                                         last step): never the home, never a protected branch; judged like git push
run("git", "mr_open", {title, ...})      after the user's Cho phép on its full text (a one-use pass of exactly that
                                         text): the merge request through GitLab REST (utils/git/gitlab.py); push
                                         and merge request kept in pl_git_audit
Stop                                     the turn does not end while a code file of the plan changed since the last
                                         green verify (stop.unverified, gear/detect/stop.py; a repeated Stop ends it;
                                         a failure to look keeps it)
run("plan", "plan_close", {summary?})    the close form with the facts of the ledger (Đóng plan "<title>" (<pd-id>)
                                         [<ticket>]?: commits, files vs plan, verify, skipped); only the answer closes:
                                         Đã giao (delivered), Bỏ plan (abandoned); Giữ mở keeps it open
run("ledger", "plans_settle", {...})     the open desk plans and their proof; write ends the proven ones, drop ends
                                         unproven plans of dead sessions after the user's Cho phép
delivery (utils/plan/closing.py)         the commit is judged by what it holds: HEAD's parent is the commit of the
                                         approval, and it changes only plan files (paths as git names them, case
                                         kept), each as the passing verify saw it, a plain file whose mode does not
                                         change; anything else is not delivered, and the model is told
```
A ticket (`pl_tickets`, `utils/plan/tickets.py`) runs each approved plan: the approval opens it in phase `execute`
(an open ticket with no plan is reused, a revision keeps its ticket and `rootId`, another plan closes the open one
`superseded` and carries its done steps and commits), `step_done` closes it `delivered` (a home plan needs no form).
`tickets.approved_plan(ticket)` is the one rule for a plan in force; `LedgerPort.approved` reads only it. The MCP
server knows its session from the hook: the session whose prompt or harness tool call came last (`sessions`).

Every commit from the shell is refused (`commit.raw`): `git commit`, and any line that may commit another way. A
commit made around the gate (a shell form the reader does not know) can still land in the repository; delivery
judges it by what it holds, and anything but the verified change is never delivered as the plan's.
`tests/e2e/test_flow.py` runs this whole flow with the hook and the MCP server as processes, on a git repository.

What the gates refuse, so they always see what they judge:
- A form whose answers the model filled in, or with a question or option label that holds `"="` (built to look like
  an answer). The response text is read for an answer only when nothing holds `"="` and each question is found once,
  at the start or after `: ` or `, `.
- Every line with git (in Bash or PowerShell) that may commit. Before step_done the reader let through one plain
  `git [-C dir] commit` with options from a short list
  (`-m`, `-F`, `-q`, `-s`, `-v`, `--message`, `--file`, `--quiet`, `--signoff`, `--verbose`, `--allow-empty`). So:
  a commit joined to another command or `cd`, with environment variables, run by another program (`env`, `sudo`,
  `xargs`, `eval`, `bash -c`, `python -c`...), in a group or `if`, with a newline, `$(` or a backtick, with paths or
  any other option (an abbreviation like `--amen` too), with a global option other than `-C`, and any git
  subcommand that may commit another way (aliases, `merge`, `rebase`, `cherry-pick`, `pull`...). A line with git and
  a shell expansion (`$ { } * ? [ ~ %`) is refused too, unless it is one plain git command that makes no commit.
  A first word that is git spelled another way (`g\it`) or `git-<subcommand>` is refused; a commit in a folder that
  does not exist is outside the plan.
- The git rules (`gear/detect/git.py` on the git commands `gear/translate/git_cli.py` reads, rows in
  `gear/rules/git.json`) hold only where a protected branch is touched (`protected` in `project.json`, main and master
  by default): the repository is on one, a push names one or `--all`/`--mirror`, a `branch -d/-D/-f/-m` names one.
  There each one asks, never refuses: `git add -A`/`.` (P1), `--no-verify` or `commit -n` (P2), `reset --hard` (P3),
  a force push (P4), any write on the branch (P5), a push from the home (P6), agent files staged or pushed (P7), git
  with `-c`/`--git-dir`/`--work-tree` (P8). Elsewhere git is free.
- The git block, `run("git", "run", {repo, args})`, runs git through the harness. It judges the command as the hook
  does (`HarnessGit`, so the shell reader asks nothing of it): nothing to ask, it runs; asked, it gives the form
  question `Duyệt git <args> trong <repo> [<code>]?`, the user's approval word is kept in `pl_asks` (`utils/git/asks.py`,
  through `Act`), and the next run of exactly that command uses it up; refused (`git commit`: step_done), it never runs.
  Every run is kept in `pl_git_runs` with the rules that asked and the code of the user's word.
- The commit guards: before step_done commits, the harness judges the commit with the rules (the event
  `HarnessCommit`, `gear/translate/commit.py`): a secret in a line it adds (`gear/detect/secret.py`, commit.secret),
  an AI mark (AI co-author or footer, an AI tool's name or address, a robot emoji) or a Mermaid diagram in the message
  (`gear/detect/mark.py`, `utils/git/marks.py`, commit.ai_mark), a word of `banned` in `project.json`
  (commit.banned_word), agent files in a unit's commit (`gear/detect/agent.py`, commit.agent_files). A write into
  `.claude/rules/` (a skill instead), a `memory/` folder of `.claude` (a note instead) or the behaviour registry file
  (`add test` instead) is refused (agent.rules, agent.memory, agent.registry).
- A plan path inside `.git`, with `~`, `%` or a comma, or a title with a double quote.
- Paths are compared as the system resolves them: real paths (8.3 short names expanded), without a `\\?\` prefix.

## The shell reader
A Bash or PowerShell call is read before it runs, so a write by the shell meets the same gate as Write/Edit.
- `utils/shell/scan.py` splits the line as its shell does (bash, PowerShell, cmd): commands, quotes, escapes,
  redirections, heredocs. `utils/shell/words.py` takes the wrappers off (`sudo`, `env`, `timeout`, `xargs`...) and reads
  again the string a shell runs (`sh -c`, `eval`, `powershell -Command`, `cmd /c`, a shell fed a heredoc).
- `utils/shell/place_ops.py` (git lines: `git_ops.py`) looks each real command up: a known read writes nothing; a known write names its files
  (operands, redirections, the destination of a copy, the file of a download); after `cd X` a relative path is
  read from both folders. Text in quotes or in a heredoc body is no command.
- What it cannot see whole is unread: an unknown command or script, a target the shell makes (`$F`, `*.py`, `~`),
  a command run inside a word (`$( )`, backticks), inline code that may write, git that changes the work tree.
- An unread call asks the user (`shell.unread`) in Claude Code's own prompt, with the agent's words on what it does
  (the tool's `description`), the command, the files the reader saw and what it could not read. With no such words
  (fewer than three, or the command copied back) it is refused (`shell.unexplained`), and the agent writes them.
- The harness's state is shut to every tool, reads too (`read.state`): every place a shell line names
  (`utils/shell/mentions.py`: words, option values, variables, redirections, wildcards expanded on the disk, both
  folders after `cd`) and the path of Read, Grep, Glob, LS and NotebookRead. The harness's own commands
  (`python -m entry.<x>`, `python .../entry/<x>.py`) name nothing. The ledger is read only through
  `run("ledger", "db_query", {sql})`: one SELECT, opened read only, an authorizer that refuses writes, PRAGMA, ATTACH
  and the transcript tables (`tx_*`), at most 200 rows. A path the shell makes from a variable (`$D/harness.db`)
  cannot be told and gets past the reader.
- A refused write wins over the question: a write to `state/` or outside the plan is refused even when the rest of
  the line is unread.

## The connection rule
- `hooks`, `gear` and `mcp` import only themselves and `utils`. They never import each other or `assemble`.
- `utils` imports no block.
- `assemble` connects: `engine/loader.py` reads the `ITEMS` of `hooks`, `mcp` and `gear` and the action files of
  `mcp/actions/`, and loads them by name. It is the one place of a dynamic import.
- `entry/` imports only `assemble` (its doors: `engine/build.py`, `engine/wire_mcp.py`, `engine/checks.py`), and only
  inside `main()`: the top of an entry script
  imports only the standard library. A harness that does not load, or quits (SystemExit), still answers: the hook
  exits 2.
- `assemble` imports `nets` only inside `doctor()` (`engine/checks.py`). The nets are dev-time code and never weigh on a hook call.

## Indexes
`harness/hooks/__init__.py`, `harness/mcp/__init__.py` and `harness/gear/__init__.py` only declare: a docstring and one literal
`ITEMS = [{"kind", "name", "ref"}]`. The loader reads them as text and refuses:
- a kind the block does not hold;
- a missing or extra field;
- a name used twice in any block;
- a ref outside the block or to no file;
- an index with logic.

| Block | Kinds |
|---|---|
| `hooks` | `hook`, `translator` |
| `mcp` | `server`, `tool`, `source`, `table` |
| `gear` | `translator`, `detector`, `rule` |

## The run of a hook
```
Claude Code -> entry/hook.py   (standard library: the maint grant, the form, then the harness)
  -> assemble/engine/build.run_hook
  hooks/io.py: JSON -> Event
  select.py: the session's approved plan picks the pipeline (none: base, the floor); pipeline.py names the
             translators and detectors
  runner.py: translators + ports -> facts -> detectors -> findings -> gear/decide/arbiter.py -> Verdict -> Act
  hooks/io.py: Verdict -> permissionDecision (allow says nothing); the notes of Act -> additionalContext
```
- Only `gear/decide/arbiter.py` judges. A finding is looked up in `gear/rules/*.json`, and the strongest verdict wins.
- A finding that no rule names asks the user, and the question names the finding.
- A rule row names its test (`tests/.../test_x.py#test_y`), and a row whose test does not exist does not load.
- Each fact has one giver. Two that give the same fact are an error, never an overwrite.
- Ports (`assemble/engine/ports.py`) read the world for the gears: the approved plan, and the state folder.
- `Act` (in `runner.py`) writes back: an approval from the form (`utils/plan/approval.py`), a delivered plan after a
  commit (`utils/plan/closing.py`), each finding as a rule decision.
- A broken harness exits 2, which blocks the call.

## The maint grant
Only the user's "Duyệt" to `Tắt guard N phút: <why>?` turns every guard off, for at most 120 minutes. The model gets
the question from `run("maint", "grant", {minutes, why})` and `run("maint", "status")` says whether the guards are
off. The grant is a row of the ledger (`pl_notes`, kind `maint.grant`, `{"until": seconds}`), written in one
transaction with its trace in `pl_logs`: no trace, no grant. While it lasts, each call is traced in `pl_logs`.

The top of `entry/hook.py` writes and reads these rows itself, with plain `sqlite3` and the statements of
`schema.sql`, so the grant works even when the harness is broken. It is the one place outside `utils/ledger/db.py`
that opens the ledger; `tests/utils/test_grant.py` keeps its names the same as `utils/maint/grant.py`.

AskUserQuestion is let through when the harness is broken, so the user can always be asked. It is refused when the
model filled in the answers, when a question or label holds `"="`, when it is not shaped as a form, or when checking
it fails at all: only a form that passed the check may pass a broken harness. A grant that reaches further than 120
minutes is no grant, and the state folder stays closed to the editing tools while the guards are off. The hook writes
UTF-8 bytes, whatever the console's code page.

## Releases: the code a session runs
Claude Code runs `entry/boot.py <entry>`: that entry of the release in force (`state/live/<sha>/`, named by
`state/live/current`), never the work tree a session edits; with no release, the work tree's own. The entry gets the
home (`HARNESS_HOME`) and the code (`HARNESS_CODE`, read by `build.code_of`). A file a session writes into the
harness runs nowhere until `python3 -m entry.cli live publish` builds the release (`utils/gateway/release.py`), its own
doctor is clean, and the user answers Cho phép to `Cho phép phát hành harness <sha>?`. The MCP server
(`engine/live_mcp.py`) checks each new release with its doctor and swaps it in without a restart; one that fails is
never taken. `entry/boot.py`, `.claude/settings.json` and `.mcp.json` are never written in a session (agent.anchor).

## The MCP server
`entry/mcp_server.py` serves three tools over stdio (JSON-RPC 2.0):
- `find`: skills and blocks ranked by the words of the request.
- `guide`: a skill, or the actions of a block.
- `run`: one action of the action table, with its arguments checked.

A block is only the prefix of an action's name. Each file of `mcp/actions/` holds one literal
`ACTIONS = [("block.name", "Class"), ...]` (a file may hold several blocks), read by `engine/loader.py` from its syntax
tree. Each class is a `McpAction` (`utils/contracts.py`): `block`, `name`, `summary`, `args_schema` (a JSON schema),
`needs` and `effect` (`read` or `write`); it gets an `ActionContext` and raises `ActionError`. The ports are
`ACTION_PORTS` and `SERVER_PORTS` (`engine/ports.py`, built in `engine/wire_mcp.py`); the doctor checks each action
against its entry, its effect and its ports, and `tests/mcp/test_action_registry.py` pins the list.

`run` (`mcp/tools/run.py`): an unknown action, arguments that do not fit `args_schema`, or a port the server lacks is an
error before anything runs; the action gets only the ports in `needs`. A `write` is judged first: the judge port runs
the hook's own pipeline on the event `mcp__harness__run` `{block, action, args, effect: write}`; the detector
`write_action` reports `action.<block>.<name>`, and only an allow a rule row of `gear/rules/actions.json` decided lets
it run. An ask, a refusal, an allow no rule decided (`write-unjudged`) or a judge that fails stops it. A `read` is never
judged.

| Block | Actions |
|---|---|
| `plan` | `plan_present`, `plan_revise`, `plan_show`, `plan_status`, `plan_drop` |
| `verify` | `run` |
| `plan` | `step_done`, `step_skip`, `plan_close` |
| `git` | `run`, `commit`, `push`, `mr_open` |
| `ledger` | `db_query`, `plans_settle` |
| `maint` | `grant`, `status` |
| `health` | `items`, `doctor` |

## Ledger
`state/harness.db` is made from `utils/ledger/schema.sql`, a whole copy of the real ledger's schema v5.
- A DB with no table (new, or left empty by a crash) gets the schema in one transaction.
- Each open compares its fingerprint (tables, indexes, views, triggers, with comments and spaces taken out).
- Every write is one transaction.
- Rows of `rec_plans`, `rec_commits`, `pl_verify` (and the other audit tables) carry a hash chain over every column,
  the id too. The chain proves no row was changed, not that none was taken off its end.
- A row is never changed: the state of a plan is its events (`waiting`, `approved`, `delivered`).

The doctor compares the real ledger (`ledger` in `project.json`, an absolute path) with `schema.sql`, read only, and
names each table, index, view or trigger that is missing, extra or written another way. It never writes the real
ledger: at rest (no `-wal`, no `-journal`) it reads it as immutable, so no file is made beside it; in use it reads it
through its `-wal` and `-shm`, and only the `-shm` (the readers' shared index) may change. A ledger it cannot read
(no file, an empty file, not a database, a `-wal` without its `-shm`, a writer still at work after the read) is an
ERROR, never a match. The path is this machine's: where it does not exist, the doctor says so.

## Nets
`entry/doctor.py` (also `run("health", "doctor")`) reports every problem as an ERROR, in this order:
- the indexes;
- each item's ref, which must load;
- the build (config, pipeline, rules), and each action file, which must load;
- the skill library: each skill reads, its name is its folder's, and no name is used twice;
- the real ledger's schema, when `project.json` names it;
- then every net.

The nets read the whole tree except two places, and only these: `state/` (the private DB) and
`project/behaviors.json` (the old harness's record of the tests here, until the cutover).

| Net | Rule |
|---|---|
| `layout` | a file is only where `nets/layout.json` allows (`*` stays in one folder, `**` crosses folders) |
| `imports` | the connection rule above, aliases and relative imports included; dynamic imports only in the loader; a file that does not parse |
| `bridges` | no file only passes names on |
| `size` | `.py` at most 400 lines, `.md` at most 300 |
| `verdict` | outside `gear/decide/arbiter.py` and `utils/contracts.py`: no verdict word (allow, ask, refuse, deny), no `ALLOW`/`ASK`/`REFUSE`, no `Verdict` |
| `config` | `project.json` is named only in `assemble/engine/config.py` |
| `entry` | an entry script imports only the standard library at load time (in `try`, `if`... too); its `main()` catches `BaseException` |

The nets read the code as written, not as it runs. A name built at run time (`getattr(m, "AL" + "LOW")`) gets past
them. Review keeps that out, and no net claims to.

A file that does not decode as UTF-8 is reported by `size`, and a file that does not parse by `imports`. No net
crashes on it. An index or a skill that does not decode is also reported by the loader or the skill library, which
need it. The nets read `harness/`, `entry/` and `nets/`. A test file that does not parse is shown by the test run
itself.

## How to add a thing
1. Write the test first, in `tests/<block>/test_<module>.py` (`tests/nets/test_tests_layout.py` checks the name).
2. Write the class in its block, a translator or a detector on the base classes of `utils/contracts.py`.
3. Declare it with one line in the block's `ITEMS`.
4. Name it in a pipeline (`assemble/pipelines/`), and give each finding it reports a rule row in `gear/rules/`, with its test.
5. Run the tests and `entry/doctor.py` until both are clean.
