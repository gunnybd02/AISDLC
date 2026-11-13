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
run("plan", "plan_present", {plan})      the revision waits in the ledger; its root is the MCP server's folder (the
                                         project); the answer is the form question, which names the files and the root
                                         (with plan_id: a new revision of a waiting plan; only the newest is approvable)
AskUserQuestion                          the user answers; only "Duyệt" to that exact question approves it
Write / Edit, or a write by the shell     allowed only for the files of the approved plan (detect/tracked.py, detect/planfiles.py)
run("verify", "run", {plan})             the unit's tests in the plan's root; the receipt keeps each file's blob id,
                                         read before and after the tests (a file that changed under them: no pass)
run("steps", "step_done", {plan, message})
                                         the harness checks, then commits: the plan approved and its repository still
                                         on the commit of the approval, a passing verify, each plan file as the verify
                                         saw it, no secret in a changed file; it stages and commits only the plan's
                                         changed files (utils/plan/steps.py, the one writer of commits)
delivery (utils/plan/closing.py)         the commit is judged by what it holds: HEAD's parent is the commit of the
                                         approval, and it changes only plan files (paths as git names them, case
                                         kept), each as the passing verify saw it, a plain file whose mode does not
                                         change; anything else is not delivered, and the model is told
```
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

## The MCP server
`entry/mcp_server.py` serves three tools over stdio (JSON-RPC 2.0):
- `find`: skills and blocks ranked by the words of the request.
- `guide`: a skill, or the actions of a block.
- `run`: one action of the action table, with its arguments checked.

Each block of actions is a file of `mcp/actions/` that declares `BLOCK`, `ABOUT` and `ACTIONS = [Class, ...]`. The
loader reads these by the file's syntax tree; `engine/wire_mcp.py` gives each action only the ports it names in
`needs` (`plans`, `verify_command`, `state_dir`, `items`, `doctor`). The logic sits in `utils/plan/`:

| Block | Actions |
|---|---|
| `plan` | `plan_present`, `plan_status` |
| `verify` | `run` |
| `steps` | `step_done` |
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
