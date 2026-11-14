# Migration map: flat `.claude/` -> block folders

Where each file of today's tree goes in the target layout (the "How it sits in Claude Code" design), what has to be
split, and every hard-coded path that breaks when files move. Paths are relative to `.claude/`.

Today: 3 blocks (`mcp`, `gear`, `assemble`) + `utils`, one flat folder each, 6 284 lines.
Target: 5 blocks (`hooks`, `gear`, `mcp`, `assemble`, `utils`) with sub-folders.

## 1. File moves

`=` moves as is (path and imports change only) · `split` the file is cut in two or more · `new` no file today.

### entry/
| Today | Target | |
|---|---|---|
| `entry/hook.py` | `entry/hook.py` | = (keeps `CLAUDE_DIR = parent.parent`) |
| `entry/mcp_server.py` | `entry/mcp_server.py` | = |
| `entry/doctor.py` | `entry/doctor.py` | = |
| — | `entry/boot.py`, `cli.py`, `git_hook.py`, ... | new, later rows |

### harness/gear/ -> gear/translate, gear/detect, gear/decide
| Today | Target | |
|---|---|---|
| `gear/translate_git.py` | `gear/translate/git.py` | = (`git_cli.py` comes later) |
| `gear/translate_place.py` (447 lines, over the 400 cap) | `utils/shell/place_ops.py` + `utils/shell/git_ops.py` + `gear/translate/place.py` | split: tables and `*_targets`, `sed`, `curl`, `cmdlet`... (lines 18-415) are policy-free -> `place_ops.py`; `GIT_NO_FILES`, `GIT_GLOBAL`, `git()` -> `git_ops.py`; only `class Places(Translator)` stays in gear |
| `gear/translate_answer.py` | `hooks/forms.py` | = but changes block: form answers belong to the `hooks` block in the target. Its gear item `answers` is removed from `gear/__init__.py` and declared in `hooks/__init__.py` |
| `gear/detect_plan.py` | `gear/detect/tracked.py` (`plan.none`) + `gear/detect/planfiles.py` (`plan.outside`, `write.state`) | split. Path helpers `key`, `named`, `rel_key`, `relative`, `PREFIXES` -> `utils/plan/files.py` (both detectors and the commit gate use them). Form findings (`form.prefilled`, `form.forged`) -> `hooks/forms.py`. Shell findings (`shell.unread`, `shell.unexplained`) -> stay in `planfiles.py` |
| `gear/detect_commit.py` | **no home in the target** | decide: (a) `gear/detect/commit.py` + a `layout.json` row, or (b) fold into `utils/plan/steps.py` / git tool so commits go only through `step_done`. Today it imports `harness.gear.detect_plan`; after the split it imports `harness.utils.plan.files` |
| `gear/decide.py` | `gear/decide/arbiter.py` | = ; `RULES = ("harness","gear","rules")` still right |
| `gear/rules/plan.json` | `gear/rules/place.json` (plan/write/shell rows) + `sessions.json`/forms rows | split by finding |
| `gear/rules/commit.json` | `gear/rules/git.json` | = then P1-P8 rows added |

### harness/mcp/ -> mcp/server, mcp/tools, mcp/actions, mcp/skills, and the new hooks block
| Today | Target | |
|---|---|---|
| `mcp/hooks.py` (`HookIO`) | `hooks/io.py` | = , new block `hooks` |
| `mcp/stdio.py` | `mcp/server/stdio.py` | = |
| `mcp/tool.py` | `mcp/server/tool.py` | = |
| `mcp/find_tool.py` | `mcp/tools/find.py` | = |
| `mcp/guide_tool.py` | `mcp/tools/guide.py` | = |
| `mcp/run_tool.py` | `mcp/tools/run.py` | = |
| `mcp/skills.py` | `mcp/skills/library.py` | = |
| `mcp/actions.py` (`ActionTable`) | `mcp/actions/table.py` | = , but its role changes: it collects `ACTIONS = [...]` from each `mcp/actions/*.py` by AST instead of `add_block()` calls |
| — | `mcp/server/stamp.py` | new |

### harness/assemble/ -> assemble/engine, assemble/pipelines
| Today | Target | |
|---|---|---|
| `assemble/config.py` | `assemble/engine/config.py` | = |
| `assemble/loader.py` | `assemble/engine/loader.py` | = (+ new `KINDS["hooks"]`, AST read of `mcp/actions/*.py`) |
| `assemble/ports.py` | `assemble/engine/ports.py` | = |
| `assemble/runner.py` | `assemble/engine/runner.py` | = |
| `assemble/recipe.py` (`RecipeBook`) | `assemble/engine/pipeline.py` + `select.py` | rename recipe -> pipeline; `select.py` picks by plan state |
| `assemble/recipes/base.json` | `assemble/pipelines/base.json` | = |
| `assemble/build.py` | `engine/build.py` (`build_runner`, `run_hook`) + `engine/wire_mcp.py` (`action_table`, `run_mcp`) + `engine/checks.py` (`doctor`, `built`, `real_ledger`, `report`) | split |
| `assemble/blocks.py` (handlers as closures over `LedgerPort`) | `mcp/actions/plan.py` (`present`, `status`) + `utils/plan/verify.py` (`blobs`, `verify`) + `utils/plan/desk.py` (`paths`, `checked`) + pause -> **no home** (suggest `mcp/actions/maint.py`) | split; each handler becomes one action class with `needs = (...)` ports, not a closure |
| `assemble/act.py` (`Act`) | `utils/plan/approval.py` (`approvals`) + `utils/plan/steps.py` / `closing.py` (`delivery`, `not_the_plans`) | split; `act.py` imports `assemble.ports.YES` today -> `YES` must move to `utils/contracts.py` first, since utils may not import a block |

### harness/utils/
| Today | Target | |
|---|---|---|
| `utils/contracts.py` | `utils/contracts.py` | = (gains hook event names, `YES`) |
| `utils/shell_scan.py` | `utils/shell/scan.py` | = |
| `utils/shell.py` | `utils/shell/words.py` | = (`read`, `program`, `DEPTH`) |
| `utils/git_run.py` | `utils/git/run.py` (`run`, `GitError`) + `utils/git/facts.py` (`head`, `top`, `parent`, `committed`, `staged`, `blob`) | split |
| `utils/ledger/db.py`, `recorder.py`, `schema.sql` | same place | = (`turns.py` new) |

### Other folders
| Today | Target | |
|---|---|---|
| `skills/example/SKILL.md` | `project/skills/example/SKILL.md` | = |
| `project.json` | `project.json` (+ `project.sample.json` for tests) | = |
| `project/behaviors.json` | stays until the cutover | = |
| `nets/*` | `nets/*` | = , plus `english_net.py`, `resolve_net.py`, `files.py` new; `entry_net.py` has no row in the target table: keep it |
| `docs/architecture.md`, `transfer.md` | same | rewrite paths |
| — | `settings.json` here, `.mcp.json` in the root of the repository the harness is installed into | new |

## 2. Hard-coded paths and names that break

Every one of these must change in the same commit as the move it belongs to, or the doctor and nets fail.

| File:line | Today | Change to |
|---|---|---|
| `harness/assemble/build.py:15` | `CLAUDE_DIR = Path(__file__).resolve().parents[2]` | `parents[3]` (one folder deeper) |
| `harness/assemble/build.py:43` | `claude_dir / "harness" / "assemble" / "recipes"` | `.../"assemble"/"pipelines"` |
| `harness/assemble/build.py:79,110` | `claude_dir / "skills"` | `claude_dir / "project" / "skills"` |
| `harness/assemble/recipe.py:8` | `RECIPES_DIR = Path(__file__).with_name("recipes")` | `Path(__file__).parents[1] / "pipelines"` |
| `harness/assemble/loader.py:10` | `KINDS = {"mcp": (...), "gear": (...)}` | add `"hooks": ("hook", "form")`; move `hook` kind out of `mcp` |
| `harness/assemble/loader.py:107` | ref regex `harness.<block>.<a.b>:<Name>` | already accepts sub-packages; no change |
| `harness/gear/__init__.py` | 6 refs `harness.gear.translate_place:Places` ... | `harness.gear.translate.place:Places`, `harness.gear.detect.tracked:...`, `harness.gear.decide.arbiter:Decide`; drop `answers` |
| `harness/mcp/__init__.py` | 7 refs `harness.mcp.find_tool:Find` ... | `harness.mcp.tools.find:Find`, `harness.mcp.server.stdio:StdioServer`, ...; drop `hook_io` |
| — | `harness/hooks/__init__.py` | new: `hook_io` -> `harness.hooks.io:HookIO`, `answers` -> `harness.hooks.forms:Answers` |
| `nets/layout.json` | flat patterns `harness/gear/*.py` ... | `harness/gear/translate/*.py`, `harness/gear/detect/*.py`, `harness/gear/decide/arbiter.py`, `harness/hooks/*.py`, `harness/mcp/{server,tools,actions,skills}/*.py`, `harness/assemble/engine/*.py`, `harness/assemble/pipelines/*.json`, `harness/utils/**/*.py`, `project/skills/*/SKILL.md` |
| `nets/imports_net.py:8-14` | `ALLOWED` has 3 blocks | add `"hooks": ("harness.hooks", "harness.utils")`; `"entry": ("harness.assemble",)` stays |
| `nets/imports_net.py:18` | `DYNAMIC_OK = ("harness/assemble/loader.py",)` | `harness/assemble/engine/loader.py` |
| `nets/imports_net.py:23` | `owner()` = second path part | still right (`harness/<block>/...`) |
| `nets/config_net.py:6` | `DOOR = "harness/assemble/config.py"` | `harness/assemble/engine/config.py` |
| `nets/verdict_net.py:9` | `OWNERS = ("harness/gear/decide.py", ...)` | `harness/gear/decide/arbiter.py` |
| `gear/rules/*.json` `"test"` field | `tests/gear/test_place_and_plan.py#...` | the new test file of each finding (the doctor checks these links) |
| imports in every moved module | `from harness.utils.shell import ...` etc. | new dotted paths (see section 1) |
| every new sub-folder | — | needs an empty `__init__.py`; the loader must not treat it as a block index |

## 3. Tests

Target rule: `tests/<block>/test_<module>.py`, named after the module (`tests/nets/test_tests_layout.py`).

| Today | Target |
|---|---|
| `tests/gear/test_decide.py` | `tests/gear/test_arbiter.py` |
| `tests/gear/test_place_and_plan.py` (290) | `tests/gear/test_place.py`, `test_tracked.py`, `test_planfiles.py`, `tests/hooks/test_forms.py`, `tests/utils/test_place_ops.py` |
| `tests/gear/test_git_and_commit.py` (261) | `tests/gear/test_git.py` + test of wherever the commit gate lands |
| `tests/mcp/test_hooks.py` | `tests/hooks/test_io.py` |
| `tests/mcp/test_tools.py` (171) | `tests/mcp/test_find.py`, `test_guide.py`, `test_run.py`, `test_table.py` |
| `tests/assemble/test_blocks.py` | `tests/mcp/test_plan.py` + `tests/utils/test_verify.py` |
| `tests/assemble/test_act.py` | `tests/utils/test_approval.py`, `test_steps.py` |
| `tests/assemble/test_loader.py`, `test_runner.py` | same names (module names do not change) |
| `tests/utils/test_shell.py` | `tests/utils/test_scan.py` + `test_words.py` |
| `tests/utils/test_ledger.py` | `tests/utils/test_db.py` + `test_recorder.py` |
| `tests/e2e/*`, `tests/nets/test_nets.py` | stay; update path literals |

## 4. Order that keeps the tests green

Run `python3 -m unittest discover -s tests -t .` and `python3 entry/doctor.py` from `.claude/` after each step.

1. Move `YES` to `utils/contracts.py`; move the path helpers of `detect_plan.py` to `utils/plan/files.py`. No path moves yet.
2. `utils/`: `shell/`, `git/`, then split `translate_place.py` into `utils/shell/place_ops.py` + `git_ops.py`. Update `layout.json` rows for `utils/**`.
3. `gear/`: `translate/`, `detect/`, `decide/arbiter.py`; refs in `gear/__init__.py`; `verdict_net` owner; rule `"test"` links.
4. New `hooks` block: `hooks/io.py`, `hooks/forms.py`; `KINDS`, `ALLOWED`, `layout.json`.
5. `mcp/`: `server/`, `tools/`, `skills/library.py`, `actions/table.py`; `skills/` -> `project/skills/`.
6. `assemble/engine/` + `pipelines/`; fix `CLAUDE_DIR` depth, `DYNAMIC_OK`, `DOOR`. Split `build.py`.
7. Turn `blocks.py` / `act.py` handlers into `mcp/actions/plan.py` classes with `needs` and `utils/plan/*`; switch `ActionTable` to AST-collected `ACTIONS`.
8. Rename and split the tests (section 3); add `tests/nets/test_tests_layout.py`.
9. Rewrite `docs/architecture.md` and `docs/transfer.md` to the new paths.

## 5. Decisions

`Core-repo` is only a name: this repository is cloned into the repository where the user starts Claude, and the
harness works from there on other folders. Paths stay relative to `.claude/`; nothing is renamed.

| # | Question | Decision |
|---|---|---|
| 1 | Commit gate (`detect_commit.py`) | Commits go only through `step_done` / the git tool. `git.json` refuses a raw `git commit`; the checks (verify passed, files unchanged, plan files only) move to `utils/plan/steps.py`. `detect_commit.py` is removed |
| 2 | Pause | Becomes the maint grant, `mcp/actions/maint.py` + `utils/maint/grant.py` |
| 3 | Vietnamese text | `\u` escapes in `.py` files; JSON rule text stays as is |
| 4 | Verify | Stays an MCP action too (`run('verify', 'run', {plan})`), next to the CLI `verify` |
| 5 | Pipeline key | Follow the target: `select.py` picks the pipeline from the plan state; the `recipe` key leaves `project.json` |
| 6 | Entry logic, nets import | Pause logic leaves `entry/hook.py` for `hooks/forms.py`; `engine/checks.py` keeps importing `nets`, the one exception, listed in `imports_net.ALLOWED` |
| 7 | State storage | One file, `state/harness.db`; every read and write goes through it. See section 6 |
| 8 | `nets/entry_net.py` | Kept (default, not chosen by the user) |
| 9 | `translate_answer.py` | Moves to `hooks/forms.py` as the target says (default, not chosen by the user) |

## 6. One store, and the guards around it

| Topic | Before | After | Lands in |
|---|---|---|---|
| Harness data | 3 SQLite files (`harness.db`, `transcripts.db`, `overlay.db`) + JSON (`pause.json`) + image files | One file, `state/harness.db`; every read and write goes through `utils/ledger/db.py` | `utils/ledger/schema.sql` gains the `tx_*`, overlay, grant and source tables; `utils/sessions/archive.py`, `utils/overlay/journal.py`, `utils/maint/grant.py` write there |
| Reading the data | The shell can read `state/` (by accident) | Only `run("ledger", "db_query")`; a shell line that touches `state/` is refused | `gear/rules/place.json` (read and write of `state/` refused); `mcp/actions/ledger.py` |
| Transcripts | `transcripts.db` | `tx_*` tables in `harness.db`; `sessions.reopen` works as before; `db_query` cannot read the `tx_*` tables | `utils/sessions/archive.py`; `mcp/actions/ledger.py` refuses a query naming `tx_` (checked on the parsed SQL, with an authorizer, not on the text) |
| Jira/Confluence images | Files in `state/twg/sources/` | BLOBs in SQL; when one must be seen, the harness writes it to a temp file | `utils/twg/open.py`, `utils/twg/page.py`; temp file outside `state/`, removed after use |
| Writes into `.claude/rules/`, `memory/`, the registry (block `__init__.py`, `ACTIONS`) | Passed silently | Refused, with the right way named: a skill, the notes tool, `add test` | `gear/detect/agent.py` or a new rows set in `gear/rules/place.json`, each with its own `why` |
| Playwright / CDP into a signed-in browser | Allowed freely | A UAT plan names `cdp` in its network section; a plan that has it runs the whole plan without asks; without it, refused | `gear/translate/net.py` + `net_hosts.py` (find CDP: `connect_over_cdp`, `--remote-debugging-port`, `ws://.../devtools`); `gear/rules/net.json`; `utils/plan/desk.py` (network section) |
| Harness commands, e.g. `HARNESS_DB=... python3 -m entry.cli verify` | Run | Still run as before | `gear/translate/place.py` keeps reading the harness's own CLI as a known command, so the `state/` refusal does not catch it |

What stays a file, because it is not data:
- `state/live/<sha>/`: the built releases are Python code that `entry/boot.py` imports.
- `project.json`: config, written by the maintainer.

Moves in section 1 that change because of this:
- `assemble/ports.py:38` keeps `state/harness.db`, but the path comes from `HARNESS_DB` through `engine/config.py` only.
- `pause.json` (`assemble/blocks.py:119`, `entry/hook.py`) is gone; the maint grant is a row.
- No `transcripts.db` or `overlay.db` is ever created; `utils/ledger/db.py` is the only code that opens SQLite, a net
  (`nets/imports_net.py`, or a new `sqlite_net.py`) keeps it so.


## 7. Status

Steps 1 to 9 are done on branch `refactor/block-folders`. Tests: every test passes on Windows and on Linux; one
(`\\?\` prefixes and 8.3 names) runs on Windows only. Tests write Windows paths through `tests.native()`, which keeps
them on Windows and drops the drive elsewhere; cases that only Windows has (a case folded drive, `\` as the
separator, a Git Bash `/c/` drive) run on Windows only. Two fixes in the code came with it: a Windows ledger path in
`project.json` loads on every system and names no ledger off Windows (`Config.ledger_here`), and a Git Bash drive
(`/c/x` read as `C:/x`) is read only on Windows (`utils/shell/paths.py`).

Where the result differs from section 1:
- `gear/detect/forms.py` holds `form.prefilled` and `form.forged`: detectors live only in gear.
- `mcp/actions/health.py` keeps `items` and `doctor`; `mcp/actions/verify.py` keeps `run` (decision 4).
- `Act` sits in `assemble/engine/runner.py` (no `act.py`); its logic is `utils/plan/approval.py` and `closing.py`.
- `mcp/actions/maint.py` serves the maint grant (`grant`, `status`).
- The size net is 400 lines for `.py`, as the target says (it was 500).

Done in 7d:
- Commits only through `step_done` (`mcp/actions/steps.py`, `utils/plan/steps.py`, `utils/git/commit.py`): the model
  calls it, the harness checks verify, plan files and secrets, then commits or refuses. `gear/detect/commit.py` stays
  as one finding, `commit.raw`, which `git.json` refuses for every commit from the shell. The secret scan is a short
  list of patterns for now; `gear/detect/secret.py` (transfer.md row 3) replaces it.
- The maint grant replaces pause (`mcp/actions/maint.py`, `utils/maint/grant.py`): a `pl_notes` row of kind
  `maint.grant` and its trace in `pl_logs`, existing tables of schema v5, so the schema still matches the real
  ledger. `entry/hook.py` reads and writes them with plain `sqlite3`, so the grant works when the harness is broken
  (the user's decision); `pause.json` and `pause.log` are gone.
- The state is shut (section 6, row "Reading the data"): `read.state` refuses every tool that names a place in
  `state/`, reads too (`utils/shell/mentions.py`, `gear/detect/planfiles.py`); `run("ledger", "db_query")`
  (`mcp/actions/ledger.py`, `query` in `utils/ledger/db.py`) is the one read-only door, and never reads `tx_*`.

- MCP actions in the shape of `docs/mcp.md`: `ACTIONS = [("block.name", "Class")]`, `McpAction`, `ActionContext` and
  `ActionError` in `utils/contracts.py` with `effect`, `ACTION_PORTS`/`SERVER_PORTS` in `engine/ports.py`, the judge
  of write actions in `mcp/tools/run.py` (rule rows in `gear/rules/actions.json`), the pinned registry test.

- Plan lifecycle (docs 04), part 1: the ticket (`utils/plan/tickets.py`, `pl_tickets`): phases prepare, execute,
  deliver; close delivered, superseded; `approved_plan` as the one rule; the calling session of the MCP server.

- Plan lifecycle, part 2: the desk (`utils/plan/desk.py`: items, limits, clean, normalize, merge, tiers), the block
  and form (`render.py`), revisions (`revisions.py`: sha of the block, feedback, dropped), and the actions
  `plan_present`, `plan_revise`, `plan_show`, `plan_status`, `plan_drop`. Paths stay relative to the root (no `~/`,
  `/` or globs yet: those come with the files gate); `services` other than none/agent-code wait for declared units.

Left for 7d, each waits for the feature it stores:
- One store, the rest of section 6: transcripts in `tx_*` tables, overlays, Jira/Confluence images as BLOBs. None
  of these features is in this harness yet; each lands in `harness.db` when it moves in.
