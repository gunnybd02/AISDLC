# 05 - Orchestra, sections 8 to 12

> The second half of the user's spec (`05-orchestra.md` holds sections 1 to 7), saved as pasted on 2026-11-15.

## 8. Watch

`python3 -m entry.cli orchestra watch [--interval S] [--max MIN]` (alias `wait children`; defaults 60 s, 480 min;
`cli_wire.py:46,92-111`), run in the background. `watch.run` (`watch.py:159-191`):

| Exit | When |
|---|---|
| 0 | every spawned child stopped: the digest |
| 2 | bad flag, no session port, or no open delegated plan (no `pl_waits` row) |
| 3 | `--max` ran out: who still runs (and "sessions could not be read" when blind), then the digest |
| 4 | an open question (`asks`): at once, before any sleep |

`reason` (`watch.py:64-78`), first match: settled state; handed back newer than `sentBackAt`; list unreadable -> only
`idle`; listed row in `done`/`stopped`/`failed`; not listed -> `exited`; state `blocked`/`needs_input`/`waiting` ->
"waiting on a prompt"; no activity for 30 min (`IDLE_MS`; `pl_turns`: an open turn is now) -> `idle`. A child never spawned
does not hold the watch; with none spawned it waits to the limit. Rows match by sid, or by a listed sid starting with the
`bg` id. One `pl_waits` row per wait (outcome done/timeout/error). Digest line: name | reason | commits (7-char shas) |
verify | AC n of m (as check counts) | extras (extra child, faults, added) | not checked | tokens (`pl_usage`) | turns,
plus refused prompts.

## 9. Reach: messages, respawn, land (`reach.py`)

- Sessions: `snap` = `claude agents --json --all --cwd <home>` rows {sid, job, name, state, ...}; an unreadable list raises
  `SessionsUnreadable` (never an empty list). `job_of` gives the id `claude stop|rm` take.
- `deliver` (`:69-91`): live row -> `send`, which the CLI cannot do (`host.py:115`), so the answer says "tell <name> with
  SendMessage" (SendMessage to an active background child passes the message gate); ended row -> `claude --bg --resume <sid>
  <text>` by the real session id (`session_id`: crew sid, row sid, else the transcript starting with `bg`); an adopted
  ended session is not resumed. Delivered texts go to `entry.sent`.
- `respawn {name, reportTo?}` (`crew_reach.py`, `reach.py:99-130`): refused for an adopted or ended child, an unreadable
  list, a row still running unless `orphaned` (`blocked` with no job), or no known session id ("forget it and spawn it
  again"). Resumes the same id with a fresh brief (current parent name, its worktree); entry `running`, `sentBackAt` = now
  (an old handback no longer stops the watch), row `running` why `respawned`.
- `land {name, why?}` (`reach.py:133-160`): for a child whose session stopped before handing back: refused when ended,
  list unreadable, still running, no commits, no open worktree, dirty files, or `check.run` not green; else `_merge` and
  `_accepted` as accept.

## 10. Release, forget, remove, purge

| Action | Effect | Refused when |
|---|---|---|
| `release {name, why}` | entry `released`, child ticket closed `released`, plan not ended, session untouched | no why; already ended |
| `forget {name, why?, plan?}` | entry `forgotten`, ticket closed, plan `dropped`; a spawned session stopped (`claude stop <job>`); `after_end` clears `--bg` worktree and gives up `wt/p<N>` (branch with own commits archived first) | not in crew |
| `remove {name?, why?, plan?}` | needs a one-use pass `child-remove:<name>` from ONE checklist form (`form_marks.remove_list_call`, options = children not running and not removed); entry `removed`, ticket closed, plan dropped; spawned session `claude stop` + `claude rm`, transcript deleted with usage kept (`purge.forget`); worktree given up | named child running or removed; nothing removable |
| `purge` (`crew_purge.py`) | every child session on disk that stopped for good, after one Yes/No form naming 8-char prefixes (one-use pass `orchestra-purge:`): usage into `pl_usage`, transcript and folder deleted, job removed, crew entries removed, open child tickets closed `removed` | none found; never a non-child, an adopted session, a child of an open delegated plan (`purge.live`), the caller, or any listed session; unreadable list refuses |

`plan` reaches an older delegated plan of the session by number (`Crew.parent(plan=...)`, renumbered numbers resolved).

## 11. Lineage of superseded tickets (`lineage.py`)

A new delegated plan approved while children work (only a revision is allowed now) closes the old ticket `superseded`;
the new one carries the crew; a carried child keeps the old parent id and its card stays in the old grant.

- `lineage(conn, body)` (`:30-33`): body + closed `superseded` delegated tickets of the session that are its own chain:
  same `draft` (a revision), or `_carried` (same name with the same `bg` or `sid`; a name spawned again is not a carry).
- `card_of`: the card and the plan number of the ticket that holds it. `follower`: the open ticket that carried `name`
  (a handback updates it). `Crew.child_ticket`: newest child ticket whose `parent` is any id of the chain.
- `renumbered(conn, sid, n)` (`:60-69`): `pl_plan_events` approved `ref = n` -> its draft -> newest delegated ticket of that
  draft; `status {plan: n}` says "plan N became plan M".
- `status {plan?}`: one line per child: session (+ listed state), phase, plan, behaviours, commits, verify, state (+ end
  why, sent back n x), handback; carried entries marked; open questions after.

## 12. Bugs paid for, open gaps, watch-for

Longer entries: `.claude/debug/harness-orchestra.md` (JS live runs, plans 588-701, and notes).

### Python harness (2026-11)

| Bug | Root cause | Fix |
|---|---|---|
| Eight children each ran the full suite at once and killed the machine | no shared verify lock, no cap | `VerifyLock` flock in the git common dir; spawn capped at 3 running (`8151e7e7`) |
| A child could not edit, verify or commit in its card | card plan only moved, never opened | take opens it with `PlanOpening`, `approvedBy grant:` (`e8b3b332`), in its own `wt/pN` (`80a4113f`) |
| A child in `wt/pN` hit permission prompts; a forgotten child could not restart | home allow rules do not reach the worktree | `--permission-mode auto --add-dir <roots>`; forgotten name gets a fresh card (`b89f4e88`) |
| A failed `claude agents --json` marked every child `exited`; adopt could resume a live session | an unreadable list returned `[]` | `SessionsUnreadable`; watch counts only idle then (`ad4bb1e8`) |
| `check` after a revision found no AC | the parent was renumbered, the card ids were not | `card_plan_no` reads the card's own number (`7feada66`) |
| `remove` could delete a session under its work | no state filter | only children not running (`c9a7dccf`) |
| A child plan stayed open after accept/forget | the child's session stops, nothing ended its plan | `ending.end_plan` from the parent's call; worktree given up, reap for orphans (`cb4f4868`) |
| Purge took children still working, or still listed | prefix match only | `purge.live` and "any listed session stays" (`a9e24f3a`, `1772893d`) |
| Reject/answer text never reached the child | no deliver path; `--resume` took the job id | `deliver`, respawn by real session id, briefs name the parent by session id, `land` (`4b50ea2f`, `02781f5c`) |
| Carried children lost card and ticket in a new plan | lineage not read | `lineage.card_of` / `follower` (`b1bf5608`); new plans now blocked while delegated runs (`7753555e`) |
| `status {plan: old}` failed; close form counted other plans' children | revision renumbers; lineage read every superseded ticket | own chain only, `renumbered` (`8c846739`) |
| Two children hung `blocked` at start with no job; respawn said "running" | blocked was taken as alive | `orphaned` = blocked with no job (`8c846739`, not yet proven live) |
| A delegated parent never closed itself | `uncovered` ignored the parent's step; step_done stopped at Deliver | Deliver means own step done; `close_home` with `Crew.done` (`00fbc9db`) |
| Every child commit refused after plan tiers | card plans opened with no `pipeline_of`: no `scope.profile` | openers pass `pipeline_of` (`73c4bfda`) |
| A child's verify upgraded the live ledger | live `HARNESS_DB` in the child's test run | verify and finish on a ledger copy (`d07bd309`, `bced1801`) |

### Classes carried from the JS runs (still guarded)

| Class | Python guard |
|---|---|
| A refused spawn left a session running | every refusal before `create`; a failed save stops the session |
| A child took the parent's `p<plan>` worktree | brief names its own worktree; take answers with it |
| A card AC like "works" passed review | `FILLER` rule: >= 2 content words |
| `check` green on uncommitted work | `dirty` fails check and land; accept merges commits only |
| Behaviour ids collided across plans (`ac1`) | ids `p<plan>.<name>.ac<n>` |
| A handback older than a send-back stopped the watch | `sentBackAt` compared in `handed_back` |
| A finish busy on another session's lock was blamed on the child | `busy` -> "retry accept, do not send it back" |
| Removals asked 3 forms | one checklist; one-use passes spent only by a removal that ran |
| A note per child woke the parent repeatedly | handback answer and brief say "no message"; one digest |

### Open gaps

| Gap | Where | Effect |
|---|---|---|
| No code refuses `AskUserQuestion` in a child | only the brief says so (`card.py:150`) | a child that asks waits for nobody; watch reports "waiting on a prompt" or idle |
| `send` cannot reach a live session | `host.py:115` | reject/answer to a running child say "tell it with SendMessage": the parent must send it |
| `Crew.uncovered` ignores the parent's own commits | `crew.py:382-391` | last accept before the parent step says "waits"; do the parent step last or after |
| `accept` runs the release's `finish.py` but the child's tests | `finish.py` | a new refusal in the child's suite blocks its own accept (plan 1110); make such gates additive |
| `check` runs only the AC tests | `check.py` | the full suite runs at finish; a test outside the AC can fail the merge |
| `orphaned` respawn not proven live | `reach.py:94-96` | until proven: forget and hand the card to a new child |
| A child can write in another plan's worktree | sandbox allows all of `<home>-wt/` | the JS guard `bash-other-worktree` is not ported |
| A child stalled on an API error shows `running` | watch sees only listed state and 30 min idle | it holds the watch until idle or `--max` |
| A parent with no own behaviour cannot `add file` | `grants.py` | out-of-plan docs of a parent go to a revision or a later plan |

### Watch-for

- Test an action through the real ports (`mcp_call`, hook look + anchor), not a hand-built port map: every JS live fault
  passed a unit test with a full fake ledger.
- An action with a side effect outside the ledger (a session, a worktree) says every refusal first.
- `check` proves only the tests the child wrote: read `notChecked` and the risks before accepting.
- Key anything durable by `draft`, card plan number or the lineage chain, never by the parent's current plan number.
- Never present another plan while a delegated plan runs; revise it.
- Read the Claude Code docs before relying on a sandbox or CLI behaviour (`git -C`, pipes, `send`).
