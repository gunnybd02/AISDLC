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
  project.json  the values of the user (name, recipe)
  skills/       the skill library, served by find and guide
  docs/         this file and transfer.md
  tests/        one folder per block, plus e2e/
  state/        private, not in git
```

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
Claude Code -> entry/hook.py -> assemble.build.run_hook
  mcp/hooks.py: JSON -> Event
  config.py (recipe name) + recipe.py (translators, detectors by name)
  runner.py: translators -> facts -> detectors -> findings -> gear/decide.py -> Verdict
  mcp/hooks.py: Verdict -> permissionDecision (allow says nothing)
```
- Only `gear/decide.py` judges. A finding is looked up in `gear/rules/*.json`, and the strongest verdict wins.
- A finding that no rule names asks the user, and the question names the finding.
- A rule row names its test (`tests/.../test_x.py#test_y`), and a row whose test does not exist does not load.
- Each fact has one translator. Two translators that give the same fact are an error, never an overwrite.
- A broken harness exits 2, which blocks the call.

## The MCP server
`entry/mcp_server.py` serves three tools over stdio (JSON-RPC 2.0):
- `find`: skills and blocks ranked by the words of the request.
- `guide`: a skill, or the actions of a block.
- `run`: one action of the action table, with its arguments checked.

The handlers of the blocks live in `assemble/build.py`. Today the only block is `health`, with `items` and `doctor`.

## Nets
`entry/doctor.py` (also `run("health", "doctor")`) reports every problem as an ERROR, in this order:
- the indexes;
- each item's ref, which must load;
- the build (config, recipe, rules);
- the skill library: each skill reads, its name is its folder's, and no name is used twice;
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
