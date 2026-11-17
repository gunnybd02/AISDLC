# 13 - The cloud harness against the foundation spec

The user's spec 13 (foundation architecture) sets the structural rules of the harness and names the failures they
prevent. This page says, for this cloud harness, which rules hold, what enforces each, where the code differs on
purpose, and what is still open. Checked on 2026-11-17 by reading the code and running the doctor and the suite.

## 1. The rules that hold

| Spec rule | Here | Enforced by |
|---|---|---|
| Five blocks (hooks, mcp, gear, assemble, utils), imports point one way, utils imports no upper block | Yes | imports net |
| Only the loader imports by name | Yes (`assemble/engine/loader.py`, `live_mcp.py`) | imports net |
| Block declaration files only declare (`ITEMS`, `ACTIONS` literals) | Yes | the loader, in the doctor |
| Every file sits where the layout list allows | Yes | layout net |
| No bridge modules | Yes | bridges net |
| At most 400 lines of Python, 300 of Markdown | Yes | size net |
| Verdict words only in the arbiter and contracts | Yes | verdict net |
| `project.json` read only by `config.py` | Yes | config net |
| Entries thin; a broken harness still answers | Yes: an entry imports only the standard library at load and catches everything | entry net |
| Every function typed and documented | Yes (beyond the spec) | hints net |
| One judge; the strongest verdict wins; a finding with no row is asked | Yes | `gear/decide/arbiter.py` and its tests |
| One owner per concept; no copies | Yes since this plan | **owners net** (section 2) |
| Policy is data | Rule rows for hook calls; the orchestra limits in `project.json` (section 3) | arbiter load; config load |
| The ledger: version and fingerprint on open, one upgrade door, hash chains, a fault never blocks | Yes | `docs/12-ledger.md`, the doctor's ledger line |
| Approval only by the form's exact "Approve" | Yes | plan tests |

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

`project.json` may hold `limits`, each a whole number from 1 to 10; a limit not given is its default.

| Limit | Default | What it bounds | Read by |
|---|---|---|---|
| `children` | 3 | children of a delegated plan running at once | spawn, started, status |
| `rounds` | 3 | send-backs of one child before the user decides | reject, and the brief that tells the child |

`config.py` is the one place the defaults live; the MCP server hands them to the actions as the `limits` port.
Two numbers stay in code on purpose: `PER_QUESTION = 4` (the form tool shows at most 4 options: a fact of the host,
not a policy) and `DEAD_AFTER` (6 hours: a guess of when a session no longer runs, not a rule anyone sets).

## 4. Where the cloud differs from the spec (open, for the user to decide)

| Spec | Here | Why it differs |
|---|---|---|
| A pipeline is self-contained, no `extends` | A plan pipeline `extends` the floor (`assemble/pipelines/`) | Built that way before spec 13 reached the cloud; changing it touches every pipeline |
| A rule row is `code, verdict, reason, when`, with facts from a declared vocabulary | A row is `finding, verdict, why, test`: detectors make named findings, rows judge them | The same: one judge and data rows, but keyed by finding |

## 5. Still open (from the check of 2026-11-17)

- **The hook's failure policy.** Spec: a broken harness blocks only PreToolUse (exit 2) and lets every other event go
  (exit 0). Here `entry/hook.py` exits 2 on every event, Stop included, so a broken harness could hold the end of a
  turn: a gate with no exit.
- **No english net.** Non-ASCII letters sit in `project/behaviors.json` and three orchestra documents.
- **The imports net is partial.** It does not refuse third-party packages outside the entries, running text as code,
  or `sys.path` edits; an entry may import any `assemble` module, not five named ones.
- **No fitness tests** (a new gear touching at most four files, a new action two).
- **Model-facing text lives beside the code.** The owners net checks the action names it gives; the sentences
  themselves still sit in `utils`, one place per answer.
- **Refusals in code.** `utils/plan` and `utils/orchestra` refuse in code (`raise ...Error`) where the hook path refuses
  through rule rows. Many are input checks; which are policy is not yet sorted.
