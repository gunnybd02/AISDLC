# 05b - Orchestra in the cloud (children as cloud sessions)

> How this harness builds the user's spec 05 (`05-orchestra.md` to `05-orchestra-4.md`), which assumes one PC.
> Decided by the user on 2026-11-16: a child is a **cloud session**; the card travels **in the brief** and the
> handback receipt **on the child's branch** (no refs of the harness on the remote); at most **3** children run; a
> live probe first, then one plan per part. All four parts are built. The cap of 3 running children and the 3
> send-back rounds are the defaults `limits.children` and `limits.rounds`, which a plan may lower (`13-cloud-foundation.md`).
> Changed by the user on 2026-11-17: parent and child **talk through git, never by message** (section 2b).
> Changed again by `system.md` (decided 2026-11-18, built by PRs 61 to 81): the parent sends the running child
> **signed orders** (fix, answer, stop) by `send_message`; a child speaks only through its branch, CI and its draft
> PR's comments; a plan with a plan branch ends with **form 2**.
> Changed by the user on 2026-11-20 (PR 95): the talk is **comments** on the child's draft PR and its issue; nothing
> under `.harness/` is committed on any branch (section 2b).
> Changed by the user on 2026-11-20 (PR 103): **children merge into main**. No plan branch: a child branches from main
> and its MR goes into main. CI is the project's own (set once per repo; a plan may write CI files as normal work; the
> harness never adds one by itself; with no CI that phase is skipped). The parent tests each MR with its own copy of
> the locked tests and merges it itself on pass (`accept`); `close` ends the plan. No harness ci, no form 2, no land.

## 1. Why spec 05 changes here

Spec 05 holds a delegated plan together with three things the cloud does not have: **one ledger** that the parent and
every child share, **worktrees** of one clone, and **`claude --bg`** that harness code calls to start a child. In the
cloud each session is a machine of its own, with its own clone and ledger, thrown away when the session ends. Two
sessions share only the git remote, and only the model (never harness code) can open or reach a session.

| Spec 05 | This harness |
|---|---|
| `spawn` starts `claude --bg` | Harness code cannot open a session. `spawn` answers the brief and the exact `create_session` call; the parent's model makes it and gives the id back with `started`. Only then does the child run, so a failed start leaves no ghost. |
| One shared ledger | The card rides in the brief (a JSON block). The receipt (commits, verify, behaviours) is posted by harness code as a JSON block in the child's handback comment on its draft PR. The crew stays in the parent's ledger (and its Drive copies). |
| Worktree `wt/p<N>` per child | Each child has its own clone and branch `orch/p<plan>/<name>`; it pushes after every step, because its machine is temporary. |
| One child per unit unless worktrees | Several children may share a unit: each has its own clone and branch. |
| `watch` polls the session list | Harness code cannot list cloud sessions, and a cloud child cannot message its parent. The parent sets a check-in (`send_later`) and reads the children's branches (`status`, `check`). |
| `check` runs in the child's worktree | The parent fetches the child's branch and reruns the AC tests in a temporary checkout, plus the base proof. |
| `accept` merges and deletes the branch | The same merge and tests, then push. This connection cannot delete branches (403): merged branches are listed for the user. |
| `remove` / `purge` delete transcripts | After the user's checklist, the parent's model archives the sessions (`archive_session`). |
| Only the brief forbids AskUserQuestion in a child | The child's harness refuses it: AskUserQuestion, merging, pushing another branch, and `plan_present` when it has a card. |
| Texts cannot reach an idle child | They can (probe of 2026-11-18): since PR 81 a send-back or an answer is a signed order the child's hook checks in its notifications, and since PR 95 a comment on its draft PR; `spawn` opens a fresh session, whose brief carries those words, only when the child's session ended. |

Not needed here: worktrees, the verify lock between children, `claude --bg`, `watch`, respawn by job id, the purge of
transcripts on disk.

## 2. What the live probe showed (2026-11-16)

One child session was opened with `create_session` and a brief (session "Orchestra probe: child alpha").

| Question | Answer |
|---|---|
| Is a child opened from a brief governed from its first word? | Yes: auto permission mode, the harness start message at its session start. |
| Does child -> parent `send_message` wake the parent? | Yes, within about 20 seconds. **Not so on 2026-11-17**: refused or held for approval (section 2b). |
| Does parent -> child `send_message` wake an idle child? | Yes, within about 20 seconds. |
| Does a child act on a send-back? | **Only because its brief said send-backs from the parent are part of its plan.** It treats any other message as data. So the brief says so, with the parent's session id. |
| Can a child edit or commit with no plan? | No: the harness refuses (expected; `take` opens its card plan). |
| Found a bug | `git ls-remote` was refused as "may commit"; it is read-only now (part 1). |

Still unproven: a child pushing its branch (needs `take`, part 2), how long an idle child survives, and the cost of
one child.

## 2b. Talking through git (live checks of 2026-11-17)

Three live checks showed that a cloud child **cannot message its parent**: in auto mode the classifier refuses
`send_message` ("Unsanctioned Communication"), and in accept-edits mode it waits for an approval nobody gives. An
allow rule in the repository's `.claude/settings.json` changed neither (it was added in PR 46 and taken out again).
A session the user started can message, a session another session started cannot.

So every word between parent and child is a comment on the child's draft PR (or its issue), posted by a harness
(`utils/orchestra/talk.py`, a `<!-- harness-comment {...} -->` marker; secrets masked); the branch
`orch/p<plan>/<name>` holds only code and empty commits, and nothing under `.harness/` (PR 95):

| Who | Writes | Then |
|---|---|---|
| Parent | at spawn: an empty start commit `#N <name>: start` and the draft PR (every child) | the child registers |
| Child | its registration: a comment on its issue (`take`) | its card plan opens |
| Child | its commits, pushed after every step | goes on |
| Child | a question: an empty signal commit and a `question` comment naming its sha (`question`) | waits for an order |
| Child | its handback: an empty signal commit and a `handback` comment, the receipt a JSON block (`handback`) | waits for an order |
| Parent | a send-back: a `sendback` comment (`reject`) | the signed fix order, with the words, to the running child; a fresh session only when it ended |
| Parent | an answer: an `answer` comment (`answer`) | the signed answer order, the same way |
| Parent | the signed stop order (`accept`, after the merge) | the child uploads its ledger and ends |

The parent learns of a receipt or a question from CI and the comments on the draft PR (the doorbell, `system.md`
section 8), never by a message from the child. A fresh session of a child gets the same brief plus the parent's last words and their comment's URL; `take`
stands on the pushed branch; `started` keeps the child's rounds and its earlier sessions.

## 3. One run

```mermaid
sequenceDiagram
    participant U as User
    participant P as Parent session
    participant G as Git remote
    participant C as Child session
    P->>U: plan_present with children, then the form
    U->>P: Approve
    P->>P: delegated ticket: grant, empty crew, a pending story row per child
    P->>P: orchestra spawn {name}: the brief and the create_session call
    P->>C: create_session(prompt = brief)
    P->>P: orchestra started {name, sid}: running (cap 3)
    C->>C: first prompt binds; orchestra take opens the card plan from the card block
    loop work
        C->>G: push orch/p<plan>/<name> after every step
        C-->>G: orchestra question: a signal commit and a comment on the draft; the child stops (optional)
        P-->>C: orchestra answer: a comment on the draft and a signed order (send_message)
    end
    C->>G: orchestra handback: a signal commit and the receipt in a comment; the child stops
    P->>G: at a check-in: fetch the branch and read its handback comment
    P->>P: orchestra check {name}: rerun the AC tests here
    alt red or AC missing
        P->>G: orchestra reject {name, why}: a send-back comment on the draft (round n of 3)
        P->>C: the signed fix order (send_message): its hook checks it, one more round
    else green
        P->>G: orchestra accept {name}: ready, merged into main at the tested commit; stop order, archive
    end
    P->>P: orchestra close: every child merged or forgotten, copies in the store
```

## 4. The parts

| Part | What it builds | State |
|---|---|---|
| 1 | Card rules, delegated opening, one delegated plan at a time, `spawn`, `started`, `status`, the brief, the `ls-remote` fix | built |
| 2 | The child: binding on its first prompt, `take`, `push`, `question`, `handback` and its receipt, the child refusals | built |
| 3 | The parent: `check`, `accept` (one pull request), `reject`, `answer`, `forget`, `read`, `close` (since PR 103: accept merges each child into main; close ends the plan) | built |
| 4 | `release`, `remove` (checklist, then archive), `digest`, the check-in, receipts kept out of the base, the `orchestrate` skill | built |

## 5. Part 1, as built

**Card** (`utils/orchestra/card.py`). The rules of spec 5.1: a name of a-z, 0-9 and -, unique; a unit that is home,
`none`, `agent-code` or a declared unit; a goal of at most 200 characters (a `|` becomes `/`); 1 to 6 criteria of at
most 120 characters, `;` and `|` turned into `, `, each with at least two content words (the filler list of spec 5.1:
"It works as expected" names no case); read, change and tests of at most 8 paths each; an optional `session` of at
most 60 characters, named by one card only; actions only `push`. Every fault is named at once. Changed from spec 05:
several children may share a unit. Not built: the warning on a goal joined with "and".

**Grant**: the units the cards name (home left out), the number of children, a copy of every card, the actions of
each. At the opening, the change and test paths of every card join the parent plan's files and tests.

**Delegated opening** (`utils/orchestra/crew.py open_delegated`, called by `utils/plan/opening.py`). Approving a plan
with children makes the session's ticket delegated: it holds the grant and the crew (a revision keeps its crew), and
`pl_children` gets one `pending` row per child not yet in the crew. No schema change: stored ledger copies keep their
schema.

**One delegated plan at a time.** While one runs in a session, `plan_present` refuses, and the form cannot open
another plan there (`GATE: plan ... was not opened`). A revision of the running plan is allowed.

**Actions** (block `orchestra`):

| Action | Effect | What it does |
|---|---|---|
| `spawn {name, model?}` | read | The brief and the `create_session` call (title `Orchestra p<plan>: <name>`, tags `orchestra`, `orchestra:p<plan>`, the repository's origin as `source_url`, `model` Sonnet `claude-sonnet-5-5` unless named; the model gate refuses a call with no model, and asks the user's form for another model). Refused with no approved delegated plan, a name that is no child, a child that has started (not forgotten), 3 children running, or a card that names a session to adopt (adoption comes later). |
| `started {name, sid, model?}` | write | Checks all of that again in the transaction, and that the id is `session_...`, not this session, and no other child's; writes the crew entry (running, sid, rounds 0, `reportSid` the parent) and a `running` story row. |
| `status` | read | `Plan N: x of y accepted; r of 3 may run`, then `name | unit | state | session` per child. |

**The brief** (`utils/orchestra/brief.py`) begins with `child session "<name>" of the delegated plan <n>` and the
parent's session id, then: the goal and unit; `take` first and never a plan of its own; nobody at the keyboard; the
branch and pushing it after every step; that it sends no message and talks by comments its harness posts on its draft, the parent's
comments there being part of its plan; `question`; verify bare; `handback`, then stop; the files; the criteria with their behaviour ids
`p<plan>.<name>.ac<n>`; and the card block, one JSON object between `<<<harness-card` and `harness-card>>>` with plan,
draft, parent, branch, card and behaviour ids. Part 2's harness reads that block; until part 2, a child started from
a brief cannot `take`.

## 6. Part 2, as built

**Binding** (`utils/orchestra/child.py`, called by `runner.Act` at UserPromptSubmit). A session whose **first**
prompt starts `You are child session "<name>" of the delegated plan <n>` and carries a card block that names the same
child, plan and branch gets a role on its ticket (`child`: name, plan, draft, parent, branch, card, behaviour ids).
Only the first prompt counts: a later one (a message from another session among them) never makes a session a child.
Whoever opens a session writes its first prompt: the user or one of their sessions.

**Actions of a child** (`utils/orchestra/work.py`):

| Action | What it does |
|---|---|
| `take` | Stands on `orch/p<plan>/<name>` (local, else the remote one tracked, else new from HEAD) and opens the card plan, approved **by the grant** of the parent plan: `rec_plans` says reason `grant`, the logs say `grant`, no form is recorded. The card plan: title `<name>: <goal>`, files the change paths, tests the test paths, one step committed as the goal, one behaviour per AC (id `p<plan>.<name>.ac<n>`, what `AC<n>: ...`, the first card test; registered at once when there is one). A card without `change` is refused (and `spawn` refuses it in the parent: a cloud child's plan is built from those paths). |
| `push` | Pushes its own branch only, judged by the git rules like `git push` in a shell (a refusal or a question stops it: nobody answers in a child), kept in `pl_git_audit`. |
| `question {question}` | Kept on the child's ticket (`asks`), an empty signal commit judged by the commit rules, then a `question` comment on its draft naming that commit (a failed post undoes the commit), then the push; the child stops. Named `question`, not `ask`: the verdict net keeps the word `ask` for the arbiter. |
| `handback {changed, checked, notChecked, risks, testsChanged, added?, faults?}` | Checks the report (spec 11.4: at most 10 entries of 200 characters, 400 for two-part ones). Adds what harness code reads: commits and their files, the newest verify (ok, red, missing), the behaviours `p<plan>.<name>.ac*`, uncommitted files, the base. Makes an empty signal commit judged by the commit rules, posts the report and the receipt (a JSON block) as a `handback` comment naming it (a failed post undoes the commit), pushes the branch, and tells the model to stop: it sends no message. |

**Child refusals.** `plan_present`, `plan_close` and `maint grant` refuse in a child. The translator `child_calls`
(when rows) refuses `child.ask_user` (AskUserQuestion), `child.merge` (git merge, pull, rebase) and `child.push_other` (a push to
another branch, `--all`, `--mirror`, `--tags`). **Nobody is asked in a child** (spec 11.2; found by the live run,
where a child hung on `python3 -m unittest` and on `git push`): `child_calls` gives `child.no_keyboard` on each call
of a child, and the arbiter counts it only when the call would ask (`IN_PLACE_OF_ASK`); then the call is refused with
"go on, name it under notChecked", the question's reason after it. Each such step is kept (`act_rule_decisions`, the
tool and the first word only) and listed under `refused` in the receipt. Not refused yet: leaving its branch by
`git switch`.

**Fixed by the live run.** A child's card plan no longer closes itself after its last `step_done` (a plan of the home
did): it waits in deliver for `push` and `handback`. A child keeps its role and questions on any new ticket of its
session (`tickets.CARRIED`). The brief says to run verify from the shell (`python3 <core>/anchor.py cli verify`):
through the MCP tool it stops at 60 s, and a suite can take longer.

**Units, for any repository** (since PR 61: the plan's `repos`, `utils/orchestra/card.plan_units`; before, `units` of
the removed `project.json`). A unit is a project the
plans and children work on: its repository (`repo`, an https URL; none: the home's own), its folder in it (`path`;
several units may share one repository, each with its own folder), its test command (`verify`; default the config's)
and the branch its pull requests target (`base`; default `main`). A card's unit must be declared, or `home`. `spawn`
puts the unit in the card block (a child's harness runs with its own config, not the parent project's) and opens the
child on the unit's repository; `take` roots the card plan in the unit's folder and gives it the unit's verify
(`plan["verify"]`, set by the server, never by the model; `utils/plan/verify.command_of`); the receipt names the unit.

**A limit of the cloud.** The harness's home there is the installed copy (`/root/.harness`), so a clone of this
repository is a unit: a child that changes files under `.claude/` is refused at commit (`commit.agent_files`).
Children cannot develop the harness itself in the cloud yet.

## 7. Part 3, as built

The parent reads no code; every fact comes from the child's branch (`utils/orchestra/review.py`, `fetch.py`,
`land.py`; actions in `mcp/actions/orchestra_parent.py`). GitHub is reached through `gh api` (REST,
`utils/git/github.py`, the port `github`): logged in on a PC, given its credentials by the proxy in the cloud.

| Action | What it does |
|---|---|
| `check {name, timeoutMin?}` | The project's CI on the PR head first (`doorbell.ci_state`, every check run and status): red refuses with the failed checks, running waits, none (no CI) is skipped; a draft with no CI yet is made ready once. Then a temporary checkout of the child's branch merged with the newest base (a conflict is refused with its files): a detached worktree of the parent's clone when the unit lives there, else a shallow clone of the unit's repository. The parent's own copy of the locked tests (the ledger) is written over the checkout before they run. Refused when the draft holds no handback comment of the child, a question comment is newer, the handback's signal commit is not the branch tip (then the receipt would not describe the code), the receipt is not of this child of this session, or it is not newer than the last send-back. Counts one active behaviour with a test per AC (`AC<n>:` at the start of its description), and **reruns the tests** with the unit's command in the unit's folder (once per test file when the command names `{test}`), without the harness's variables. Green only with no AC missing, nothing uncommitted, the child's verify ok and the rerun green; the result is kept on the crew entry (`lastCheck`, `checkedAt` = the round) with a `checked` story row. |
| `accept {name}` | A green check this round, the PR head still the tested commit and its base the unit's base; makes the draft ready, then **merges it into the base** (`PUT pulls/<n>/merge` at the tested sha, in harness code: the user's plan approval covers it, and the merge gate still asks for any other merge). The child is `accepted` and merged; the answer gives its signed stop order and its `archive_session` call. GitHub's automatic delete of head branches removes the branch. |
| `reject {name, why}` | Round n of 3, then the user decides; an accepted child whose pull request is not merged may be sent back too. Posts the send-back as a comment on the child's draft and gives the signed fix order for its running session (PR 81); a fresh session (`spawn`, `started`) only when that session ended. |
| `answer {name, text}` | The reply to a child's question, kept and posted as an answer comment on its draft, with the signed answer order, as for reject. |
| `forget {name, why}` | The child ends `forgotten`; its card may be spawned again. Its session stays until the user agrees to archive it. |
| `read {name}` | The receipt, read from the child's handback comment. |
| `close` | Refused while a child is neither merged nor forgotten. Then the parent's own files committed (or none), each child's ledger copy in the store (or the user's waiver), the plan closed **delivered**, and the archive calls left. Replaces `land` and form 2 (PR 103). |

Not built: the base proof of spec 14.6 (a test already green on the base).

## 8. Part 4, as built

`utils/orchestra/cleanup.py`; actions in `mcp/actions/orchestra_parent.py`; the parent's procedure is the skill
`orchestrate` (`guide("orchestrate", "skills")`).

| Action | What it does |
|---|---|
| `release {name, why}` | The child's session is the user's again, with its branch and plan; it leaves the crew (`released`). |
| `remove` | For forgotten or released children (accept gives a merged child's archive call). Which child sessions are archived is the user's word, each time. With no pass it answers ONE checklist form (one multi-select question per 4 children that ended: accepted, forgotten, released); the hook's Act keeps a one-use pass in `pl_asks` for each child the user ticks; the next `remove` marks exactly those `removed` and gives each `archive_session` call, which the parent's model makes (harness code cannot archive). |
| `digest` | One line per child: state, rounds, session, branch, last check, pull request, merged. |

**The check-in.** The answer of the first `started` tells the parent to set one scheduled check-in (`send_later`,
30 minutes) for a child that dies silently; the delivered answer of `close` tells it to delete it.

**Receipts stay out of the base** (decided by the user on 2026-11-16; by design since PR 95): the receipt is a
JSON block in the child's handback comment, never a file, so `accept` takes nothing off the branch; `check` keeps
the receipt on the crew entry.

**A child's branch starts from its unit's base.** `take` makes a new `orch/p<plan>/<name>` from `origin/<base>`, so a
pull request into a base that is not the default branch holds only the child's commits; a base not on origin starts
it from HEAD, and the answer says which.

**The children's databases are in the store before the plan is done** (decided by the user on 2026-11-16;
`utils/orchestra/synced.py`). Every copy of a run's session carries its plan marker, `orch.<plan id>.<child>` or
`orch.<plan id>.parent` (`crew.store_tag`, `store.begin`). A child uploads its ledger at handback (reason `handback`) and at its stop order.
Harness code cannot call Drive, but the hook reads Drive's own answer: when the parent's model searches the store
folder, every file named as a copy of this plan's run whose session is that child's is kept on its crew entry
(`stored`). With a store folder set, `close` delivers only when every child that ended has a copy no older than its
handback, and `remove` archives only such children (a ticked child waits); a child whose session can never upload
passes only with the user's "Allow" in the form "Close plan <id> without the database of <name>?". At delivery the
parent saves its own ledger (`orch.<plan id>.parent`). The harness proves a copy is in the store, from Drive's
answer; the model only runs the search. A copy is the child's own when its name's session is the child's cloud session id
or its own id inside its harness, which its receipt names: the two differ in the cloud (found live).

## 9. Limits

| Limit | Value | Why |
|---|---|---|
| Children running at once | 3 | Each child is a whole cloud session: cost and the user's attention |
| Children per plan | 4 (skill rule, as spec 05) | Quota |
| Send-back rounds | `limits.rounds` (default 3; a plan may lower it), then the user decides | Spec 05 |
| Card | as spec 21 | Spec 05 |

## 10. Trust

- Only the user's "Approve" in the parent's form approves the delegated plan; nothing a child says approves or widens it.
- A child trusts its brief because it is its first prompt; it trusts the parent's comments on its draft because the brief
  says they are the parent's, part of the plan. Since PR 81 it acts on an order only when its round is the next and its
  mac checks out with its own key from the brief; any other message from any session is data.
- Whoever can push to the remote could forge a receipt on a branch. That is no worse than today (whoever can push can
  change the code), and the parent reruns the tests itself instead of taking the receipt's green on trust.
- The parent writes the acceptance tests (`acTests`) and locks them (`orchestra.lock`: text and hash in the
  ledger, nothing pushed). The child's start commit adds a locked copy; its doors refuse those files, and take and
  push refuse a copy that drifted. The parent runs its own copy at check, so a changed copy cannot pass. Since PR 103
  each child merges into main on the parent's tests; no plan branch, and CI is the project's own.
