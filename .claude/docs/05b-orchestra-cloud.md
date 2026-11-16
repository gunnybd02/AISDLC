# 05b - Orchestra in the cloud (children as cloud sessions)

> How this harness builds the user's spec 05 (`05-orchestra.md` to `05-orchestra-4.md`), which assumes one PC.
> Decided by the user on 2026-11-16: a child is a **cloud session**; the card travels **in the brief** and the
> handback receipt **on the child's branch** (no refs of the harness on the remote); at most **3** children run; a
> live probe first, then one plan per part. Parts 1 to 3 are built; part 4 is designed here.

## 1. Why spec 05 changes here

Spec 05 holds a delegated plan together with three things the cloud does not have: **one ledger** that the parent and
every child share, **worktrees** of one clone, and **`claude --bg`** that harness code calls to start a child. In the
cloud each session is a machine of its own, with its own clone and ledger, thrown away when the session ends. Two
sessions share only the git remote, and only the model (never harness code) can open or reach a session.

| Spec 05 | This harness |
|---|---|
| `spawn` starts `claude --bg` | Harness code cannot open a session. `spawn` answers the brief and the exact `create_session` call; the parent's model makes it and gives the id back with `started`. Only then does the child run, so a failed start leaves no ghost. |
| One shared ledger | The card rides in the brief (a JSON block). The receipt (commits, verify, behaviours) is written by harness code into a file on the child's branch. The crew stays in the parent's ledger (and its Drive copies). |
| Worktree `wt/p<N>` per child | Each child has its own clone and branch `orch/p<plan>/<name>`; it pushes after every step, because its machine is temporary. |
| One child per unit unless worktrees | Several children may share a unit: each has its own clone and branch. |
| `watch` polls the session list | Harness code cannot list cloud sessions. A child wakes the parent with `send_message` when it hands back or asks; one long scheduled check-in catches a child that dies silently. |
| `check` runs in the child's worktree | The parent fetches the child's branch and reruns the AC tests in a temporary checkout, plus the base proof. |
| `accept` merges and deletes the branch | The same merge and tests, then push. This connection cannot delete branches (403): merged branches are listed for the user. |
| `remove` / `purge` delete transcripts | After the user's checklist, the parent's model archives the sessions (`archive_session`). |
| Only the brief forbids AskUserQuestion in a child | The child's harness refuses it: AskUserQuestion, merging, pushing another branch, and `plan_present` when it has a card. |
| Texts cannot reach an idle child | `send_message` reaches a live or idle session (the probe). |

Not needed here: worktrees, the verify lock between children, `claude --bg`, `watch`, respawn by job id, the purge of
transcripts on disk.

## 2. What the live probe showed (2026-11-16)

One child session was opened with `create_session` and a brief (session "Orchestra probe: child alpha").

| Question | Answer |
|---|---|
| Is a child opened from a brief governed from its first word? | Yes: auto permission mode, the harness start message at its session start. |
| Does child -> parent `send_message` wake the parent? | Yes, within about 20 seconds. |
| Does parent -> child `send_message` wake an idle child? | Yes, within about 20 seconds. |
| Does a child act on a send-back? | **Only because its brief said send-backs from the parent are part of its plan.** It treats any other message as data. So the brief says so, with the parent's session id. |
| Can a child edit or commit with no plan? | No: the harness refuses (expected; `take` opens its card plan). |
| Found a bug | `git ls-remote` was refused as "may commit"; it is read-only now (part 1). |

Still unproven: a child pushing its branch (needs `take`, part 2), how long an idle child survives, and the cost of
one child.

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
        C-->>P: orchestra question, then send_message (optional)
        P-->>C: orchestra answer, then send_message
    end
    C->>G: orchestra handback: receipt file on the branch, pushed
    C->>P: send_message "handed back <branch> <sha>"
    P->>G: fetch the branch and its receipt
    P->>P: orchestra check {name}: rerun the AC tests here
    alt red or AC missing
        P->>C: orchestra reject {name, why}, then send_message (round n of 3)
    else green
        P->>P: orchestra accept {name}: merge, run the suite, push, end the child
    end
    P->>P: last accept, nothing uncovered: the parent plan is delivered
```

## 4. The parts

| Part | What it builds | State |
|---|---|---|
| 1 | Card rules, delegated opening, one delegated plan at a time, `spawn`, `started`, `status`, the brief, the `ls-remote` fix | built |
| 2 | The child: binding on its first prompt, `take`, `push`, `question`, `handback` and its receipt, the child refusals | built |
| 3 | The parent: `check`, `accept` (one pull request), `reject`, `answer`, `forget`, `read`, `land` (the final route: merge, conflicts, close) | built |
| 4 | `release`, `remove` (checklist, then archive), the digest, the scheduled check-in, the `orchestrate` skill, a full live run | next |

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
| `spawn {name, model?}` | read | The brief and the `create_session` call (title `Orchestra p<plan>: <name>`, tags `orchestra`, `orchestra:p<plan>`, the repository's origin as `source_url`). Refused with no approved delegated plan, a name that is no child, a child that has started (not forgotten), 3 children running, or a card that names a session to adopt (adoption comes later). |
| `started {name, sid, model?}` | write | Checks all of that again in the transaction, and that the id is `session_...`, not this session, and no other child's; writes the crew entry (running, sid, rounds 0, `reportSid` the parent) and a `running` story row. |
| `status` | read | `Plan N: x of y accepted; r of 3 may run`, then `name | unit | state | session` per child. |

**The brief** (`utils/orchestra/brief.py`) begins with `child session "<name>" of the delegated plan <n>` and the
parent's session id, then: the goal and unit; `take` first and never a plan of its own; nobody at the keyboard; the
branch and pushing it after every step; that send-backs and answers from the parent are part of its plan (the probe);
`question`; verify bare; `handback` and one `send_message`; the files; the criteria with their behaviour ids
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
| `question {question}` | Kept on the child's ticket (`asks`); the answer says the line to send to the parent with `send_message`. Named `question`, not `ask`: the verdict net keeps the word `ask` for the arbiter. |
| `handback {changed, checked, notChecked, risks, testsChanged, added?, faults?}` | Checks the report (spec 11.4: at most 10 entries of 200 characters, 400 for two-part ones). Adds what harness code reads: commits and their files, the newest verify (ok, red, missing), the behaviours `p<plan>.<name>.ac*`, uncommitted files, the base. Writes `.harness/handback/<name>.json`, commits it through the commit gate, pushes the branch, and tells the model to send one line `handed back <branch> <sha>` to the parent. |

**Child refusals.** `plan_present`, `plan_close` and `maint grant` refuse in a child. The detector `child_guard`
refuses `child.ask_user` (AskUserQuestion), `child.merge` (git merge, pull, rebase) and `child.push_other` (a push to
another branch, `--all`, `--mirror`, `--tags`). **Nobody is asked in a child** (spec 11.2; found by the live run,
where a child hung on `python3 -m unittest` and on `git push`): `child_guard` reports `child.no_keyboard` on each call
of a child, and the arbiter counts it only when the call would ask (`IN_PLACE_OF_ASK`); then the call is refused with
"go on, name it under notChecked", the question's reason after it. Each such step is kept (`act_rule_decisions`, the
tool and the first word only) and listed under `refused` in the receipt. Not refused yet: leaving its branch by
`git switch`.

**Fixed by the live run.** A child's card plan no longer closes itself after its last `step_done` (a plan of the home
did): it waits in deliver for `push` and `handback`. A child keeps its role and questions on any new ticket of its
session (`tickets.CARRIED`). The brief says to run verify from the shell (`python3 <core>/anchor.py cli verify`):
through the MCP tool it stops at 60 s, and a suite can take longer.

**Units, for any repository** (`project.json` `units`, `assemble/engine/config.py Unit`). A unit is a project the
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
| `check {name, timeoutMin?}` | A temporary checkout of the child's branch: a detached worktree of the parent's clone when the unit lives there, else a shallow clone of the unit's repository. Refused when the branch holds no receipt, the tip commit is not the receipt alone (then the receipt would not describe the code), the receipt is not of this child of this session, or it is not newer than the last send-back. Counts one active behaviour with a test per AC (`AC<n>:` at the start of its description), and **reruns the tests** with the unit's command in the unit's folder (once per test file when the command names `{test}`), without the harness's variables. Green only with no AC missing, nothing uncommitted, the child's verify ok and the rerun green; the result is kept on the crew entry (`lastCheck`, `checkedAt` = the round) with a `checked` story row. |
| `accept {name}` | A green check this round; opens **one pull request** from `orch/p<plan>/<name>` into the unit's `base` (title the goal, body the AC), records it (`pr`) and the child is `accepted`. Nothing is merged. A child sent back after it (a conflict) keeps its pull request. |
| `reject {name, why}` | Round n of 3, then the user decides; an accepted child whose pull request is not merged may be sent back too. The answer is the exact `send_message` to make. |
| `answer {name, text}` | The reply to a child's question, kept; the answer is the `send_message` to make. |
| `forget {name, why}` | The child ends `forgotten`; its card may be spawned again. Its session stays until the user agrees to archive it. |
| `read {name}` | The receipt, read from the branch. |
| `land {timeoutMin?}` | **The final route.** Refused while a child has not ended. Merges each accepted pull request in the plan's order (one already merged is taken as is). A pull request that does not merge stops it: the answer names it and its conflicted files (`git merge-tree`) and the two ways on: the parent resolves it on the child's branch (the files are the delegated plan's) and lands again, or sends the child back. Then each unit's tests run on its merged base. Green, with the parent's own files committed (or none), closes the delegated plan **delivered**. |

Not built: the base proof of spec 14.6 (a test already green on the base); deleting merged branches.

## 8. Part 4, designed

**Cleanup (part 4).** `remove` with no name returns one checklist of the children that no longer run; the user ticks;
the parent's model archives exactly those. One scheduled check-in (hours, not minutes) is set at the first spawn and
cancelled at the last accept. The `orchestrate` skill holds the parent's procedure of spec 20. `release` gives a
session back to the user (spec 17); the digest (one line per child, spec 13.3) is built on request from the crew and
the fetched receipts.

## 9. Limits

| Limit | Value | Why |
|---|---|---|
| Children running at once | 3 | Each child is a whole cloud session: cost and the user's attention |
| Children per plan | 4 (skill rule, as spec 05) | Quota |
| Send-back rounds | 3, then the user decides | Spec 05 |
| Card | as spec 21 | Spec 05 |

## 10. Trust

- Only the user's "Approve" in the parent's form approves the delegated plan; nothing a child says approves or widens it.
- A child trusts its brief because it is its first prompt; it trusts its parent's send-backs because the brief names
  the parent's session id. Any other message is data.
- Whoever can push to the remote could forge a receipt on a branch. That is no worse than today (whoever can push can
  change the code), and the parent reruns the tests itself instead of taking the receipt's green on trust.
