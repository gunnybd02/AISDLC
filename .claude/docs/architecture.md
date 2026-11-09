# Architecture of the harness

Everything lives under `.claude/`. Python 3.13, standard library only.

```
.claude/
  entry/        hook.py, mcp_server.py, doctor.py: what Claude Code runs; they call only assemble
  harness/
    mcp/        block 1: the door to and from Claude Code; decides nothing
    gear/       block 2: translate -> detect -> decide
    assemble/   block 3: loads mcp and gear, reads the config and the recipes, runs them
    utils/      the library: shared code any block may import; it knows no rule
  nets/         the rules of the tree, checked by the doctor
  project.json  the values of the user (name, recipe, verify: the unit's test command, ledger: the real ledger)
  skills/       the skill library, served by find and guide
  docs/         this file and transfer.md
  tests/        one folder per block, plus e2e/
  state/        private, not in git: harness.db (the ledger), pause.json and pause.log
```

## The flow of a change
```
run("plan", "plan_present", {plan})      the revision waits in the ledger; its root is the MCP server's folder (the
                                         project); the answer is the form question, which names the files and the root
                                         (with plan_id: a new revision of a waiting plan; only the newest is approvable)
AskUserQuestion                          the user answers; only "Duyệt" to that exact question approves it
Write / Edit                             allowed only for the files of the approved plan (plan_gate)
run("verify", "run", {plan})             the unit's tests in the plan's root; the receipt keeps each file's blob id,
                                         read before and after the tests (a file that changed under them: no pass)
git add, then git commit -m "..."        the commit alone, in the plan's repository, after a passing verify, with the
                                         plan's files unchanged since (commit_gate)
delivery (act.py)                        by what the commit holds, however it was made: HEAD's parent is the commit of
                                         the approval, and it changes only plan files (paths as git names them, case
                                         kept), each as the passing verify saw it, a plain file whose mode does not
                                         change; anything else is not delivered, and the model is told
```
The commit gate refuses before a commit; delivery checks the result after it. A commit made around the gate (a
shell form the reader does not know) can still land in the repository, but it is never delivered as the plan's.
`tests/e2e/test_flow.py` runs this whole flow with the hook and the MCP server as processes, on a git repository.

What the gates refuse, so they always see what they judge:
- A form whose answers the model filled in, or with a question or option label that holds `"="` (built to look like
  an answer). The response text is read for an answer only when nothing holds `"="` and each question is found once,
  at the start or after `: ` or `, `.
- Every line with git (in Bash or PowerShell) that may commit, unless it is one plain `git [-C dir] commit` with
  options from a short list
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

## The connection rule
- `mcp` and `gear` import only themselves and `utils`. They never import each other or `assemble`.
- `utils` imports no block.
- `assemble` connects: `loader.py` reads the `ITEMS` of `mcp` and `gear` and loads them by name. It is the one place
  of a dynamic import.
- `entry/` imports only `assemble` (its doors in `build.py`), and only inside `main()`: the top of an entry script
  imports only the standard library. A harness that does not load, or quits (SystemExit), still answers: the hook
  exits 2.
- `assemble` imports `nets` only inside `doctor()`. The nets are dev-time code and never weigh on a hook call.

## Indexes
`harness/mcp/__init__.py` and `harness/gear/__init__.py` only declare: a docstring and one literal
`ITEMS = [{"kind", "name", "ref"}]`. The loader reads them as text and refuses:
- a kind the block does not hold;
- a missing or extra field;
- a name used twice in any block;
- a ref outside the block or to no file;
- an index with logic.

| Block | Kinds |
|---|---|
| `mcp` | `hook`, `server`, `tool`, `source`, `table` |
| `gear` | `translator`, `detector`, `rule` |

## The run of a hook
```
Claude Code -> entry/hook.py   (standard library: the pause, the form, then the harness)
  -> assemble.build.run_hook
  mcp/hooks.py: JSON -> Event
  config.py (recipe name) + recipe.py (translators, detectors by name)
  runner.py: translators + ports -> facts -> detectors -> findings -> gear/decide.py -> Verdict -> act.py
  mcp/hooks.py: Verdict -> permissionDecision (allow says nothing); the notes of act -> additionalContext
```
- Only `gear/decide.py` judges. A finding is looked up in `gear/rules/*.json`, and the strongest verdict wins.
- A finding that no rule names asks the user, and the question names the finding.
- A rule row names its test (`tests/.../test_x.py#test_y`), and a row whose test does not exist does not load.
- Each fact has one giver. Two that give the same fact are an error, never an overwrite.
- Ports (`assemble/ports.py`) read the world for the gears: the approved plan, the state folder, and `commit_view`,
  which reads git only when the call is a commit.
- `act.py` writes back: an approval from the form, a delivered plan after a commit, each finding as a rule decision.
- A broken harness exits 2, which blocks the call.

## The pause
Only the user's "Duyệt" to `Tắt guard N phút: <why>?` pauses every guard, for at most 120 minutes. The top of
`entry/hook.py` does it, so it works even when the harness is broken. While paused, each call is written to
`state/pause.log`, and the pause itself is traced before it is written: no trace, no pause. AskUserQuestion is let
through when the harness is broken, so the user can always be asked. It is refused when the model filled in the
answers, when a question or label holds `"="`, when it is not shaped as a form, or when checking it fails at all:
only a form that passed the check may pass a broken harness. A `pause.json` that reaches further than 120 minutes is
no pause, and the state folder stays closed to the editing tools while the guards are paused. The hook writes UTF-8
bytes, whatever the console's code page.

## The MCP server
`entry/mcp_server.py` serves three tools over stdio (JSON-RPC 2.0):
- `find`: skills and blocks ranked by the words of the request.
- `guide`: a skill, or the actions of a block.
- `run`: one action of the action table, with its arguments checked.

The handlers live in `assemble/` (`blocks.py`, `build.py`):

| Block | Actions |
|---|---|
| `plan` | `plan_present`, `plan_status` |
| `verify` | `run` |
| `harness` | `pause`, `pause_status` |
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
- the build (config, recipe, rules);
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
| `size` | `.py` at most 500 lines, `.md` at most 300 |
| `verdict` | outside `gear/decide.py` and `utils/contracts.py`: no verdict word (allow, ask, refuse, deny), no `ALLOW`/`ASK`/`REFUSE`, no `Verdict` |
| `config` | `project.json` is named only in `assemble/config.py` |
| `entry` | an entry script imports only the standard library at load time (in `try`, `if`... too); its `main()` catches `BaseException` |

The nets read the code as written, not as it runs. A name built at run time (`getattr(m, "AL" + "LOW")`) gets past
them. Review keeps that out, and no net claims to.

A file that does not decode as UTF-8 is reported by `size`, and a file that does not parse by `imports`. No net
crashes on it. An index or a skill that does not decode is also reported by the loader or the skill library, which
need it. The nets read `harness/`, `entry/` and `nets/`. A test file that does not parse is shown by the test run
itself.

## How to add a thing
1. Write the test first, in the block's folder under `tests/`.
2. Write the class in its block, a translator or a detector on the base classes of `utils/contracts.py`.
3. Declare it with one line in the block's `ITEMS`.
4. Name it in a recipe, and give each finding it reports a rule row in `gear/rules/`, with its test.
5. Run the tests and `entry/doctor.py` until both are clean.
