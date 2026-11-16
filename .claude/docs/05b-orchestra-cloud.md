# 05b - Orchestra in the cloud (children as cloud sessions)

> How this harness builds the user's spec 05 (`05-orchestra.md` to `05-orchestra-4.md`), which assumes one PC.
> Decided by the user on 2026-11-16: a child is a **cloud session**; the card travels **in the brief** and the
> handback receipt **on the child's branch** (no refs of the harness on the remote); at most **3** children run; a
> live probe first, then one plan per part. Parts 1 and 2 are built; parts 3 and 4 are designed here.

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
    U->>P: Duyet
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
| 3 | The parent: `check`, `accept`, `reject`, `answer`, `land`, `forget`, `release`, `read`, the digest, the parent's close | next |
| 4 | `remove` (checklist, then archive), the scheduled check-in, the `orchestrate` skill, a full live run | |

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
another branch, `--all`, `--mirror`, `--tags`). Not refused yet: leaving its branch by `git switch`; Claude Code's
own permission prompts in a child are not denied.

**A limit of the cloud.** The harness's home there is the installed copy (`/root/.harness`), so a clone of this
repository is a unit: a child that changes files under `.claude/` is refused at commit (`commit.agent_files`).
Children cannot develop the harness itself in the cloud yet.

## 7. Parts 3 and 4, designed

**`answer`** (part 3) sends the parent's reply with `send_message`. A message is a knock, never the proof: every fact
the parent acts on comes from the branch.

**`check` (part 3).** Fetch the branch; read the receipt (refused when it is missing, does not name the branch tip,
or names uncommitted files); count one registered behaviour per AC (description starting `AC<n>:`, not retired, with
a test); rerun those tests in a temporary checkout of the branch against a copy of the ledger; for a home child,
rerun them at the base (green there is a warning, as spec 14.6). Green only with no AC missing, nothing red, nothing
uncommitted.

**`accept`.** A handback, a green verify in the receipt, a green check this round; merge the branch into the base,
run the configured tests on the result, push; end the child (its crew state, a story row), and close the parent
when every child has ended and nothing is uncovered (spec 16). The branch is listed for the user to delete.

**`reject` / `answer`.** Round n of 3, then the user decides. The text goes out with `send_message`; the child acts
on it because its brief said so.

**`land`, `forget`, `release`, `read`, digest.** As spec 17 and 18, with "stop the session" read as "the parent's
model archives it". The digest is built on request from the crew and the fetched receipts.

**Cleanup (part 4).** `remove` with no name returns one checklist of the children that no longer run; the user ticks;
the parent's model archives exactly those. One scheduled check-in (hours, not minutes) is set at the first spawn and
cancelled at the last accept. The `orchestrate` skill holds the parent's procedure of spec 20.

## 8. Limits

| Limit | Value | Why |
|---|---|---|
| Children running at once | 3 | Each child is a whole cloud session: cost and the user's attention |
| Children per plan | 4 (skill rule, as spec 05) | Quota |
| Send-back rounds | 3, then the user decides | Spec 05 |
| Card | as spec 21 | Spec 05 |

## 9. Trust

- Only the user's "Duyệt" in the parent's form approves the delegated plan; nothing a child says approves or widens it.
- A child trusts its brief because it is its first prompt; it trusts its parent's send-backs because the brief names
  the parent's session id. Any other message is data.
- Whoever can push to the remote could forge a receipt on a branch. That is no worse than today (whoever can push can
  change the code), and the parent reruns the tests itself instead of taking the receipt's green on trust.
