# 05 - Orchestra (delegated plans with children)

> The user's spec, saved as pasted on 2026-11-15. It describes the user's own Core-repo harness: the paths, line
> numbers and commit ids are of that tree. It is not built in this repository yet (`docs/handover.md`).

One approval of the user covers a **delegated plan**. The parent session (the orchestrator) plans; each child is a
background session that works inside its card; the parent checks each child against its acceptance criteria (AC), merges
it and closes the plan. The parent never reads child code: it counts registered behaviours and reruns their tests. All
state is in the ledger. Paths are relative to `Core-repo/.claude/`.

Code: `harness/utils/plan/children.py` (card item), `harness/utils/orchestra/` (`crew.py`, `card.py`, `grant.py`,
`check.py`, `handbacks.py`, `asks.py`, `watch.py`, `reach.py`, `lineage.py`, `ending.py`, `leftover.py`, `purge.py`);
actions `harness/mcp/actions/orchestra.py`, `crew_reach.py`, `crew_purge.py`; sessions port `harness/utils/sessions/host.py`;
worktrees `harness/utils/worktree/engine.py`, `finish.py`, `resolve.py`. Skill: `project/skills/orchestrate/SKILL.md`.

## 1. One run

```mermaid
sequenceDiagram
    participant U as User
    participant P as Parent (orchestrator)
    participant H as Harness (ledger, worktrees)
    participant C as Child (background session)
    P->>H: plan_present with children
    H-->>U: approval form
    U->>H: Duyệt
    H->>H: delegated ticket, pending rows, card plans under card:<plan>:<name>
    P->>H: orchestra spawn {name, reportTo}
    H->>C: claude --bg --permission-mode auto, brief as first prompt
    C->>H: first prompt binds (bind_first); orchestra take opens card plan + wt/p<N>
    loop work
        C->>H: add test, verify, commit in its worktree
        C-->>H: orchestra ask (optional: watch returns at once, exit 4)
        P->>H: orchestra answer {name, text}
    end
    C->>H: orchestra handback (no message)
    P->>H: entry.cli orchestra watch (background)
    H-->>P: one digest when every spawned child stopped
    P->>H: orchestra check {name}
    alt red, dirty or AC missing
        P->>H: orchestra reject {name, why} (round n of 3)
        H-->>C: why, as a resume prompt or "use SendMessage"
    else green
        P->>H: orchestra accept {name}
        H->>H: finish wt/p<N>, child closed accepted, its plan delivered
    end
    H->>H: last accept with every child ended and nothing uncovered: parent closed delivered
```

| State of the crew entry | Set by | Ended (`ENDED`, `crew.py:31`) |
|---|---|---|
| `pending` | `card.open_all` (only a `pl_children` row; no crew entry yet) | no |
| `reserved` | `adopt` | no |
| `running` | `spawn`, `take`/`bind`, `reject` (story row says `rejected`), `respawn` | no |
| `handed back` | `handback` | no |
| `accepted` | `accept`, `land` | yes |
| `forgotten` | `forget` (may be spawned again) | yes |
| `released` | `release` | yes |
| `removed` | `remove`, `purge` | yes |

Crew entry (`crew` map on the parent ticket body): `{unit, bg, sid, state, backs, checkedAt, adopted, model, reportSid,
sentBackAt?, sent?}`. Every state change also writes one `pl_children(uid, plan_id, name, unit, state, round, sid, model,
goal, ac, why, checks, at)` row (`card._row`, `card.py:61-66`): the story, also of a child nobody remembers. `Crew` is the
single writer; each method wraps its writes in one `Recorder.transaction()`.

## 2. The card (`children.py`)

Plan item `children`; block line `- <name>: <goal> | unit: <unit or home> | ac: a; b | change: ... | tests: ... [| session:
<name>] [| actions: push]` (`lines` / `read`).

| Field | Rule (`check`, `children.py:64-109`) |
|---|---|
| `name` | `^[a-z0-9][a-z0-9-]{0,39}$`; unique; names the session |
| `unit` | a declared unit or `home`; two children on one unit only when worktrees are on for it (`tree_units`) or on the home with `home_many` |
| `goal` | required, <= 200 chars (`MAX_GOAL`); `\|` becomes `/` |
| `ac` | 1-6 (`MAX_AC`), each <= 120 chars (`MAX_AC_TEXT`); `;` and `\|` become `, `; each needs >= 2 words outside `FILLER` (it, works, done, ok, passes, test, as, expected, green, should, ...): "names no real case" |
| `read`, `change`, `tests` | paths only (`PATH_RE`: a `/` or an extension, no space), <= 8 each (`MAX_PATHS`), deduped |
| `session` | optional, `^[A-Za-z0-9][A-Za-z0-9 ._-]{0,59}$`, unique case-insensitive |
| `actions` | only `push` |
| count | `max_children` when the caller passes one |

- `grant_of(children)` (`:145-149`): `{services: units except home, actions: [], max: len, children: [copies]}`: what the
  user approves.
- `paths_of` (`:169-174`): every card's `change` and `tests` join the plan's `files` / `tests` at opening
  (`opening.py:212`), so the parent plan allows them.
- `covers(path, file)`: equal, a folder with trailing `/`, or `fnmatch`; `uncovered(files, children, except_)`: planned
  files no card covers and not in `except_`.
- `MAX_ROUNDS = 3`: send-backs before the user decides.

## 3. Opening a delegated plan

`PlanOpening._delegate` (`opening.py:281-290`), inside the opening transaction (`04-plan-lifecycle.md`):

- `kind: delegated`, `grant`, `crew` = the previous ticket's crew (a revision or a superseding plan carries it), and the same
  on `plan`.
- `card.open_all` (`card.py:69-85`): per child not in the crew and with no `pl_children` row of this plan yet: a row
  `pending`; when the card names `change` files, `_pending` keeps a **card plan** waiting under the key
  `card:<plan>:<name>` (`pending_key`): `items()` -> `desk.normalize(desk.clean())` -> rendered block -> `pl_plan_revs` rev 1
  and `pl_approval` {pending block, tool {planId, rev 1, sha}}.
- Card plan items (`card.items`, `card.py:36-54`): title = goal (<= 80), overview from goal and AC, one `code` entry per
  change file, services = `agent-code` for home else the unit, files = change, tests, one step, one behaviour per AC with id
  `p<plan>.<name>.ac<n>` (`card.id`) and what `AC<n>: <text>` (test = first card test when given).
- A child **without** `change` gets no card plan: it presents its own plan (section 4).
- While the delegated plan is open, `present_block` / `approve_block` (`approval.py:70-82`) refuse presenting or approving
  any other plan in this session (DELEGATED_PRESENT / DELEGATED_BLOCK); a revision of the running draft passes.

## 4. Spawn, adopt, take

### spawn {name, reportTo, model?, remote?, extra?} (`harness/mcp/actions/orchestra_spawn.py`)

1. `Crew.room` (`crew.py:108-113`): needs the open delegated ticket of this session (`parent`: kind delegated, grant, plan
   approved by a form, not `grant:`), `name` in the grant (or a carried card), and no crew entry unless `forgotten`.
2. At most 3 children in `running`/`rejected` (`MAX_RUNNING`; eight at once killed a 15 GB machine).
3. `reportTo` is required (adopt too); a session id becomes that session's listed name (`report_name`). A card with a `session:` line is redirected to adopt. `extra` adds ONE child, only after a handback named a fault (`harness/utils/orchestra/extra.py`; `extraFor` in the grant).
4. `sessions.create(name, brief, model, remote)` (default false; `remote: true` adds `--remote-control`, the reply shows the link read from `claude logs` or says 'NOT confirmed', `host.py`) = `claude --bg [--add-dir <enabled worktree roots>] --permission-mode
   auto --name <name> [--model m] <brief>` (`host.py:85-95`); the id is read from `backgrounded · <id>`.
5. `Crew.spawn` (`crew.py:115-126`): a forgotten name gets a fresh card plan (`card.reopen`); entry `running` with `bg`,
   `reportSid` = parent session id. If the ledger write fails the new session is stopped (or the answer says to stop it by hand).

### adopt {name, reportTo} (`harness/mcp/actions/orchestra_spawn.py`)

`room`, then `find` the session the card's `session:` line names among the listed ones; a closed session found by transcript is resumed first (refused if
it already runs in the background). `Crew.adopt`: entry `reserved`, `adopted: true`, `sid` set; one session is one child
(`reserved_for`).

### Binding and take

- **First prompt** (`grant.bind_first`, `grant.py:22-36`, called on UserPromptSubmit by the approval desk): the brief's
  words `child session "<name>" of the delegated plan <n>` bind a spawned child (entry running, no sid, has `bg`, not adopted)
  of that open parent. Binding = `grant.bind` (`:59-72`): entry `sid` + `running`, `card.bind` moves `pl_approval` and
  `pl_plan_revs` from the card key to the child sid, a fresh child ticket `{role {name, unit}, parent: <parent ticket id>,
  child: true}`, a `running` row. The card plan is bound, not opened.
- **take** (`OrchestraTake`, `orchestra.py:137-151`; `Crew.take`, `crew.py:151-167`): finds the reserved entry for this sid,
  else a running entry with no sid whose `bg` or name equals the session's listed name; binds it; `_open_card` opens the
  waiting card plan with the same `PlanOpening` a form uses, **with** the `worktrees` and `pipeline_of` ports, then
  `grant.stamp` sets `approvedBy: grant:<parent plan>`. The answer names the worktree: edit by absolute path, verify from its
  `.claude`, commit there; never `EnterWorktree`.
- **Own plan** (child without a card): `plan_present` calls `grant.grant_units` (`grant.py:39-56`, `plan.py:191-207`): a
  bound child whose services are within the grant's units (+ `agent-code`, `none`) is opened at once with no form
  ("approved inside the grant of plan X"); a unit outside: OUTSIDE; a child with a card: HAS_CARD (take instead).
- A grant-approved ticket is never taken for a parent (`parent` refuses `approvedBy: grant:`).

## 5. The brief (`card.brief`, `card.py:137-167`)

First message of a child; paths and criteria only, never code. It says:

- who it is (`child session "<name>" of the delegated plan <n>`), the parent by name **and** session id (a name changes on
  restart; `reach.parent_name` reads the current name from `reportSid`), goal, unit only;
- with a card: call `take` first, the AC ids `p<plan>.<name>.ac1..`, never `plan_present`, never `EnterWorktree`; without:
  present its own plan, approved inside the grant;
- nobody is at the keyboard: never `AskUserQuestion`, never wait for "Duyệt";
- approved actions (`push`) or "No push or MR is approved for you";
- questions go to `orchestra ask`; verify runs bare on one line (no pipe, redirect, env prefix, cd chain);
- hand back with `orchestra handback`, never message the parent;
- worktree (respawn), files to read / change, tests, each AC, "register at least one behaviour per AC", 3 rounds.

## 6. Child work, handback, ask

- The child works in its own `wt/p<card plan>` (made by take), registers behaviours (`add test`), verifies, commits
  (`step_done` / `git.commit`) like any plan. It may not finish its worktree (`worktree.py:125`), close its plan
  (`steps.py:95`), or run request actions of maint/sessions (`request-child`, `request.py:21,69`).
- **handback** {changed, checked, notChecked, risks, testsChanged, added?, faults?} (`orchestra.py:329-343`,
  `handbacks.py`): each list <= 10 points of <= 200 chars; `testsChanged` {test, why}, `added` {file, why}, `faults` {what,
  where?} (pairs <= 400); `changed` and `checked` non-empty. `Crew.handback` (`crew.py:255-271`) stores on the child
  ticket the report plus what the harness read: commits, files from `pl_git_audit` (kind commit), newest `pl_verify` of
  the child session (`ok`/`red`/`missing`), behaviours `p<plan>.<name>.ac*` (last op, retired left out), `at`. The entry of
  the parent (or of the open ticket that carried it, `lineage.follower`) becomes `handed back`. Answer: "Stop here ... no
  message".
- **read** {name, plan?}: prints it (`handbacks.read_text`), also after the plan closed.
- **ask** {question} (`asks.py`): appended to the parent ticket's `asks` `{n, name, question, at, answered: false}`; watch
  returns at once (exit 4); `status` lists open questions.
- **answer** {name, text?, plan?}: marks that child's open questions answered; with `text`, `reach.deliver` puts it to the
  child.

## 7. Check, reject, accept

### check {name, timeoutMin?} (`harness/mcp/actions/orchestra_check.py`, `check.py`)

- Refusals first: `timeoutMin` 1..30 (default 10), child spawned, handback newer than its last send-back, plan open. Needs the child's open plan; folder = `Trees.where(plan, unit)` (worktree while open, else the unit folder); `dirty` =
  uncommitted files of the worktree.
- `card_plan_no` (`check.py:34-41`): the plan number in the child's own card behaviour ids (a revision renumbers the parent,
  never the card taken); else the card's ticket number.
- `registered` (`:44-65`): latest row per id `p<n>.<name>.ac<N>`; counts when not retired, `what` starts `AC<N>:`, has tests.
- AC match: `what` regex `^\s*AC\s*(\d+)\s*[:.)-]`, case-insensitive, by number. A unit child runs tests by the `verify.units` rule (`verify_rules.runner_for`; none, or a test outside the unit: refused). Home child: after the run, `base_proof.py` reruns the tests at the worktree's base commit; a test green there is a warning. Each check keeps a `checked` `pl_children` row.
- Each distinct test runs once via `runner(test, wt)`; `default_runner` = `python3 -m unittest <module>` from the repo or its
  `.claude`, 600 s, last 1500 chars. `locate` (`:68-74`) maps a path of another worktree (`-wt/p<N>/...`) or the main repo
  (`.claude/...`) into this worktree; unplaceable fails.
- Green only when no AC missing, no red, nothing dirty; then `mark_checked`: `checkedAt = backs`.

### reject {name, why} (`crew.py:298-309`, `orchestra.py:302-313`)

Refused at `backs >= 3` ("the user decides now"). Else `backs += 1`, state `running`, `sentBackAt` = now, story row
`rejected`; `deliver` the why. The check is stale until it passes again (`checkedAt != backs`).

### accept {name, why?} (`crew.py:330-374`)

In order, nothing is settled on any refusal:

1. `not_done`: a handback exists; if there are commits, the newest verify of the child session is `ok` (else "red" /
   "missing": reject to verify).
2. `stale`: a card with AC needs `checkedAt == backs`.
3. `_merge`: when `where(plan, unit).tree`, `worktrees.finish(plan, unit)` (`finish.py`): repo lock (busy after 10 min ->
   "retry accept, do not send it back"), clean tree, ahead of base, merge base in, run the configured test on a temp ledger
   copy, fast-forward the base, delete worktree and branch. Any other failure -> "send it back".
4. `_accepted` (one transaction; `finish` is deferred, the release is published after the ledger rows): entry `accepted`, child ticket closed `accepted`, `ending.end_plan` writes `delivered` on
   each desk plan with that `ref` and no end yet (`ending.py:113-121`; forgotten/removed -> `dropped`; released -> nothing).
5. Parent: `left` = `[]` when the parent is in Deliver (its own step committed), else `uncovered(body)` (planned files no card
   and no handback covers); when `Crew.done` (every grant child ended) and nothing is left -> parent ticket closed
   `delivered`, no form. Else "waits for a file no child covers ... commit the plan's own change".
6. `leftover.after_end` (`leftover.py:195-200`): removes `<home>/.claude/worktrees/<name>` + branch `worktree-<name>` that
   `claude --bg` made (registered worktree only; `branch -d` keeps unmerged commits) and `give_up_tree` the plan worktree.

The parent's own step: `step_done` on the parent's last step calls `close_home` (`step_gates.py:35-48`), which closes a
delegated parent only when `Crew.done`. So the closing order is either "children accepted, then parent step" or "parent
step (Deliver), then last accept".

Sections 8 to 12 (watch, reach, release and removal, lineage, bugs and gaps) are in `05-orchestra-2.md`.
