# 13 - The cloud harness against the foundation spec

The user's spec 13 (foundation architecture) sets the structural rules of the harness and names the failures they
prevent. This page says, for this cloud harness, which rules hold, what enforces each, where the code differs on
purpose, and what is still open. Checked on 2026-11-17 by reading the code and running the doctor and the suite.

## 1. The rules that hold

| Spec rule | Here | Enforced by |
|---|---|---|
| Five blocks (hooks, mcp, gear, assemble, utils), imports point one way, utils imports no upper block | Yes | imports net |
| Only the loader imports by name | Yes (`assemble/engine/loader.py`, `live_mcp.py`) | imports net |
| Standard library only; no code run from a text (`exec`, `eval`, `compile`); `sys.path` only in the loader and the entries | Yes | imports net |
| An entry imports only named wiring modules | Yes: build, checks, cli_install, cli_live, cli_wire, live_mcp | imports net |
| Text is English (no letter above code point 127 outside tests) | Yes | english net |
| A broken harness blocks only a tool call (PreToolUse, or no event name); every other event goes on with the failure on stderr | Yes; an answer to a form it could not keep is told to the model | `entry/hook.py`, `tests/e2e/test_hook.py` |
| A gear that raises becomes a verdict, never a crash | Yes: `gear.fault` refuses before a tool call, `gear.fault_after` allows after it; another gear's refusal still stands | `assemble/engine/runner.py`, `gear/rules/base.json` |
| A pipeline stands alone: no `extends`; the engine puts the floor (base) under a plan's pipelines, which only add gears. A repo of the plan names its pipeline (`repos.<name>.pipeline`, shown in form 1); a plan runs the floor plus the pipelines of its services | Yes | `assemble/engine/pipeline.py` refuses `extends`; `select.py` adds the floor; the doctor reads every pipeline file and names unknown gears; a repo naming a pipeline with no file is refused when the runner is built |
| Adding a detector takes at most four files and never the runner or the arbiter; an action takes one | Yes, proven through a copied tree's own hook and MCP server | `tests/assemble/test_fitness.py` |
| Block declaration files only declare (`ITEMS`, `ACTIONS` literals) | Yes | the loader, in the doctor |
| Every file sits where the layout list allows | Yes | layout net |
| No bridge modules | Yes | bridges net |
| At most 400 lines of Python, 300 of Markdown | Yes | size net |
| Verdict words only in the arbiter and contracts | Yes | verdict net |
| No `project.json` (`system.md`, decided 2026-11-18): the plan names its repos, the repository its protection | Yes: no code reads one; the file itself goes once a release without readers is in force | `tests/nets/test_nets.py` NoConfigTest |
| Entries thin; a broken harness still answers | Yes: an entry imports only the standard library at load and catches everything | entry net |
| Every function typed and documented | Yes (beyond the spec) | hints net |
| One judge; the strongest verdict wins; a finding with no row is asked | Yes | `gear/decide/arbiter.py` and its tests |
| One owner per concept; no copies | Yes since this plan | **owners net** (section 2) |
| Policy is data | Rule rows for hook calls; the orchestra limits and banned words in the plan (section 3) | arbiter load; plan checks |
| The ledger: version and fingerprint on open, one upgrade door, hash chains, a fault never blocks | Yes | `docs/12-ledger.md`, the doctor's ledger line |
| Approval only by the user's forms (`system.md` section 10): form 1's exact "Approve" starts; a merge needs the "Allow" of its own form (the merge gate); a session on a model other than Sonnet needs its "Allow" (the model gate); the user ticks which child sessions are archived. A delegated plan has no plan branch and no form 2: accept merges each tested child (PR 103) | Yes | plan tests, `tests/gear/test_merge.py`, `tests/gear/test_session.py`, `tests/utils/test_land.py` |
| A child acts on its parent only through a signed order (HMAC with its own key), checked by its own hook | Yes (PR 81) | `utils/orchestra/orders.py`, rows `child.waiting` and `child.stopped` |

## 2. The owners net (`harness/nets/owners_net.py`)

Spec 13 names "a general duplicate net" as its first gap. The owners net reports three faults, each a way one concept
gets a second owner:

| Fault | Line it writes | The one owner instead |
|---|---|---|
| The same function body in two places (outside tests and nets; bodies of more than 120 characters of syntax, docstrings left out) | `owners: <file>:<line> <name> is a copy of <file>:<line> <name>` | import it from its owner |
| An MCP action that looks a port up, `ctx.ports.get(...)` | `owners: <file>:<line> looks a port up (ports.get)` | declare it in `needs`, read `ctx.ports[name]`: the doctor then checks the server gives it |
| A text telling the model `run('block', 'action')` for no existing action | `owners: <file>:<line> tells the model run('x', 'y'), which is no action` | rename the text with the action |

What the plan moved to one owner:

- `now()` (11 copies), `session_of(ctx)` (5), the action error wrapper (one per action file): `utils/contracts.py`
  (`now`, `session_of`, `answered`).
- The error that lists its problems (the loader's and the rules'): `contracts.ProblemsError`.
- `holds_git`: `gear/translate/git_cli.py`. One-line text: `utils/plan/item_checks.one_line`. The test tail: `fetch.TAIL`.
- The plan in force: `utils/plan/tickets.in_force` (steps and ship refuse through it).
- `land.py` runs git through `utils/git/run`; the parent's commit identity is one helper, `fetch.committer`.

## 3. Policy limits are data

A plan may hold `limits`, shown in form 1, each a whole number from 1 to its default: a plan may lower a limit, never
raise it.

| Limit | Default | What it bounds | Read by |
|---|---|---|---|
| `children` | 3 | children of a delegated plan running at once | spawn, started, status |
| `rounds` | 3 | send-backs of one child before the user decides | reject, and the brief that tells the child (its card block carries it with its order key) |

`utils/plan/item_checks.LIMITS` is the one place the defaults live; the MCP server hands them to the actions as the
`limits` port, and the actions lower them by the plan in force (`run_limits`).
Two numbers stay in code on purpose: `PER_QUESTION = 4` (the form tool shows at most 4 options: a fact of the host,
not a policy) and `DEAD_AFTER` (6 hours: a guess of when a session no longer runs, not a rule anyone sets).

## 4. Where the cloud differs from the spec

| Spec | Here | Why it differs |
|---|---|---|
| A rule row is `code, verdict, reason, when`, with facts from a declared vocabulary | Yes for every command check (PRs 54, 55): translators describe (`gear/translate/`: git_rules, action, drive, agent, child, planfiles), when rows in `gear/rules/*.json` decide; every rule action names its kind, and one that must be judged and meets no row is asked (`rule.unmatched`) | Finding rows stay for the content and state detectors (secret, mark, tracked, stop, store, forms), as spec 13 has them |

## 5. Still open (from the check of 2026-11-17)

- **Model-facing text lives beside the code.** The owners net checks the action names it gives; the sentences
  themselves still sit in `utils`, one place per answer.
- **Refusals in code.** `utils/plan` and `utils/orchestra` refuse in code (`raise ...Error`) where the hook path refuses
  through rule rows. Many are input checks; which are policy is not yet sorted.

Closed on 2026-11-17 (PR 51): the hook's failure policy, gear faults as verdicts, the english net, the whole imports
rule, and the fitness tests. Closed by PR 52: pipelines stand alone; by PR 53: a unit's pipeline came from the config
(since PR 61: from the plan's repos); by PR 54: the git rules are when rows; by PR 55: every command check is a when
row; by PR 80: every merge needs the user's Allow; by PR 81: orders, form 2 and the join (`system.md` parts 6 to 8).
