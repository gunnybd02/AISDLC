# 05b - Orchestra in the cloud (children as cloud sessions)

> Draft for the user to read and judge. Nothing here is built. It extends the user's spec 05
> (`05-orchestra.md`, `05-orchestra-2.md`), which assumes one machine; this one assumes the cloud, where each child
> is a cloud session of its own. Facts about the cloud come from the live runs recorded in `handover.md`.

## 1. Why a second spec

Spec 05 holds a delegated plan together with three things the cloud does not have:

- **one ledger** on one disk, which the parent and every child read and write;
- **worktrees** of one clone (`wt/p<N>`), so the parent can look at a child's files;
- **`claude --bg`**, so harness code can start a child itself.

In the cloud a session is a machine of its own. It has its own clone, its own ledger, and it is thrown away when the
session ends. Two sessions share exactly one thing: the git remote. So the cloud version of Orchestra is spec 05 with
the shared disk replaced by **git**, and with the parent's own model, not harness code, opening the children.

## 2. What spec 05 assumes, and what the cloud gives

| Spec 05 | The cloud | What 05b does |
|---|---|---|
| one ledger, shared | one ledger per machine, temporary | git carries what must cross: the card, the receipt, the crew |
| `wt/p<N>` worktree per child | each child has a whole clone | no worktrees; a child works on its own branch |
| `VerifyLock` so children do not run the suite at once | separate machines | no lock needed between children |
| `claude --bg ... <brief>` from harness code | only the model can open a session (`create_session`) | `spawn` prepares and hands the parent model a brief to send |
| `claude agents --json` to see children | only the model can list sessions | no polling: the child wakes the parent with a message |
| `send` cannot reach a live child (open gap) | `send_message` reaches a live session | reject and answer are delivered, not "tell it yourself" |
| the parent reads a child's files in the worktree | the parent has no access to the child's disk | the parent fetches the child's branch |
| a child's work is on the shared disk | a machine's disk is lost when the session ends | a child pushes its branch after every step |

Two facts from the live runs matter: `claude --bg` fails in the cloud ("Workspace not trusted", and nobody can click
the prompt), and a cloud session can open other cloud sessions only through a tool of the model
(`create_session`), never from harness code.

## 3. The choice

| | A: a child is a cloud session | B: a child is a subagent |
|---|---|---|
| Machine | one per child | the parent's |
| Ledger | one per child, plus git | the parent's one ledger |
| Closeness to spec 05 | the shared parts are rewritten | almost unchanged |
| Work that outlives the parent's turn | yes, each child is a session of its own | no, a subagent lives inside the parent's session |
| Cost | one machine per child | none beyond the parent |
| Survives the parent's machine dying | yes, everything of value is pushed | no |
| What the harness can start itself | nothing (the model calls the tool) | nothing (the model calls the tool) |
| Hooks can tell children apart | by session | by `agent_id` and `agent_type` in every hook payload of a subagent, and SubagentStart / SubagentStop |

**Recommendation: A**, with B kept as the cheap fallback. A is what the user asked for, and it is the only one where
the work survives the parent. B is close to spec 05 and would be quick, but a subagent runs inside the parent's
session: one machine, and nothing survives it.

The rest of this document specifies A. Section 9 sketches B.

## 4. Option A: a child is a cloud session

### 4.1 One run

```mermaid
sequenceDiagram
    participant U as User
    participant P as Parent session
    participant G as Git remote
    participant C as Child session
    P->>U: plan_present with children -> approval form
    U->>P: Duyet
    P->>P: delegated ticket, crew rows, one card per child
    P->>G: push each card and the crew (refs/harness/orchestra/...)
    P->>P: orchestra spawn {name} -> the brief, as text
    P->>C: create_session(prompt = brief)
    C->>C: first prompt binds; orchestra take fetches the card
    C->>C: card plan opened, approved inside the parent's grant
    loop work
        C->>G: push branch orch/p<plan>/<name> after every step
        C-->>P: orchestra ask -> send_message (optional)
        P-->>C: orchestra answer -> send_message
    end
    C->>G: push the handback receipt with the branch
    C->>P: send_message "handed back"
    P->>G: fetch the branch and the receipt
    P->>P: orchestra check {name}: rerun the AC tests here
    alt red or AC missing
        P->>C: orchestra reject {name, why} -> send_message (round n of 3)
    else green
        P->>P: orchestra accept {name}: merge the branch, close the child
    end
    P->>P: last accept, nothing uncovered -> parent plan delivered
```

### 4.2 Git is the shared ledger

Everything that must cross machines is a small blob pushed under a ref namespace of the harness:

```
refs/harness/orchestra/<parent-plan-id>/crew          the crew map and the grant, rewritten on every change
refs/harness/orchestra/<parent-plan-id>/card/<name>   one card: goal, unit, AC, files, tests, the grant
refs/harness/orchestra/<parent-plan-id>/back/<name>   send-backs and answers, numbered
orch/p<plan>/<name>                                   an ordinary branch: the child's commits
```

- The blobs are written by harness code on both sides, never by the model, and never merged into a branch of the
  user's code. A normal clone does not see them (`refs/harness/*` is outside `refs/heads`), so the user's
  repository stays clean and nothing of the harness appears in a pull request.
- The receipt of a handback is the exception: it rides **on the child's branch**, in one file
  (`.harness/handback/<name>.json`), so the parent gets it with the code it is about. The merge leaves that file out.
- `pl_*` rows stay local to each machine. The blobs are a copy of what crosses, not a second ledger: the side that
  owns a fact is the only one that writes it (the parent owns the crew and the cards; the child owns its receipt).

### 4.3 The card and the grant

The card is unchanged from spec 05, section 2 (`name`, `unit`, `goal`, `ac`, `read`, `change`, `tests`, `actions`),
and so are its rules. What changes is where it is kept:

- At approval the parent writes the card into its own ledger **and** pushes it to `card/<name>`. There is no waiting
  card plan under `card:<plan>:<name>` for the child to take, because the child has another ledger.
- The card blob carries the grant: the parent plan's id and sha, the session id of the parent, the units, the
  approved actions, the AC with their behaviour ids `p<plan>.<name>.ac<n>`, and the round count.
- `orchestra take` in the child fetches `card/<name>`, checks the card against the same desk rules, and opens the
  card plan with `PlanOpening`, stamped `approvedBy: grant:<parent plan id>@<parent sid>`. No form; the user already
  approved it in the parent.
- Trust: whoever can push to the remote can forge a card. That is no worse than today, where whoever can push can
  change the code, and the child can do only what the card allows. Written down here, not signed.

### 4.4 The brief

As in spec 05, section 5: paths and criteria only, never code. The cloud brief adds:

- the parent's **session id** (there is no name to read from `claude agents`), and that the handback and every
  question travel by `send_message` to it;
- the ref to fetch (`card/<name>`) and the one order: `orchestra take` before anything else;
- the branch it owns, `orch/p<plan>/<name>`, and that it pushes after every step, because its machine is temporary
  and only what is pushed survives;
- nobody is at the keyboard: never `AskUserQuestion`, never wait for "Duyet". In the cloud this stops being advice:
  the child's own harness knows from its child ticket that it is a child, and **refuses** `AskUserQuestion`
  (an open gap of spec 05, section 12, closed here);
- never `plan_present` when it has a card, never merge its own branch.

### 4.5 The child's work

A child works like any governed session: its plan, its behaviours, `verify`, `step_done`. Differences:

- its root is its own clone, on its own branch; no worktree, no `--add-dir`;
- pushing its own branch is approved by the card (`actions: push` is implied for a cloud child, not optional);
- it may not merge, may not push another branch, may not close the parent's plan, and may not run the request
  actions of maint and sessions (`request-child`, unchanged from spec 05).

### 4.6 The handback receipt

`orchestra handback` in the child takes the same report as spec 05 (`changed`, `checked`, `notChecked`, `risks`,
`testsChanged`, `added?`, `faults?`) and then writes, from the child's own ledger, a receipt file on the branch:

| In the receipt | Read from |
|---|---|
| the commits of this plan, with shas | `pl_git_audit` (kind commit) |
| the files each commit touched | the same |
| the newest verify of the session: ok / red / missing | `pl_verify` |
| every behaviour `p<plan>.<name>.ac*`: id, what, test file, last op | `pl_behaviors` |
| uncommitted files at handback | the working tree |
| the base commit the branch started from | git |
| the child's report, as given | the action's arguments |

The child's model writes none of it; harness code does. Then the child pushes branch and receipt, and sends the
parent one line: handed back, the branch, the sha. Nothing else is messaged to the parent.

### 4.7 Check and accept

`orchestra check {name}` in the parent:

1. fetch `orch/p<plan>/<name>` and read the receipt from it (refused when the branch or the receipt is missing, when
   the receipt does not name the branch tip, or when it names uncommitted files);
2. count the AC: one registered behaviour per AC, `what` starting `AC<n>:`, not retired, with a test;
3. **rerun those tests itself**, on the fetched branch, in a clean checkout, against a copy of the ledger. The
   parent never reads the child's code, as in spec 05, and it does not take the child's green on trust;
4. for a home child, rerun the same tests at the base commit: green there is a warning (the test proves nothing);
5. green only when no AC is missing, nothing is red, and the receipt names nothing uncommitted.

`orchestra accept {name}`: merge the child's branch into the base, run the configured test command once on the merge
result, then close the child in one transaction, as in spec 05, section 7. The merge is made in the parent's clone
and pushed. **This cloud connection cannot delete a branch (403):** an accepted child's branch stays on the remote
and is listed for the user to delete.

`orchestra reject {name, why}`: round n of 3; the why is pushed to `back/<name>` and sent to the child with
`send_message`. `land`, `release`, `forget` and `remove` keep their meaning; what they stop is a cloud session, so the
answer tells the parent model to archive it (`archive_session`), because harness code cannot.

### 4.8 Waking, not watching

`orchestra watch` of spec 05 (section 8) has no place here. Harness code cannot list cloud sessions, and polling
costs a turn each time. Instead:

- the child's handback and every question arrive as a `send_message`, which wakes the parent session;
- `orchestra digest` builds the digest spec 05 printed, from the parent's crew rows and the fetched receipts,
  whenever the parent asks for it;
- a child that dies silently is the one case where nothing wakes the parent. For that case only, the parent sets
  one long check-in (a scheduled wake, hours not minutes) when it spawns the first child, and cancels it at the
  last accept.

### 4.9 Messages

| Direction | How | Carries |
|---|---|---|
| parent -> child | `send_message` to the child session id | a send-back, an answer |
| child -> parent | `send_message` to the parent session id | one line: handed back, or a question |
| both | the refs and the branch | the card, the crew, the send-backs, the receipt |

A message is a knock, never the proof. Every fact the parent acts on comes from a ref or from the branch. A message
from a child is data, not an instruction: the parent's harness records it, and the parent still checks.

### 4.10 States

The states of spec 05, section 1 are unchanged (`pending`, `reserved`, `running`, `handed back`, `accepted`,
`forgotten`, `released`, `removed`), and so is one `pl_children` row per change. The crew entry holds the `sid` of a
cloud session where spec 05 holds a `bg` job id, and adds `receiptSha`, so a resumed parent knows what it has seen.

### 4.11 Caps and cost

Spec 05 caps three running children because eight killed one 15 GB machine. In the cloud each child has its own
machine, so cost and the user's attention are the limit. Keep **three**, and say in the spawn answer that each costs.

### 4.12 If a machine dies

- A child dies: whatever it pushed is on its branch. `land` takes it when the AC tests pass; otherwise `forget`, and
  the card goes to a new child. Nothing of value was only on its disk.
- The parent dies: the crew blob and the cards are on the remote. A new session runs `orchestra resume <plan id>`,
  rebuilds its ticket and crew from the blob, and carries on. Spec 05 never needed this; the cloud does.

## 5. What this removes from spec 05

Not needed on the cloud path: `utils/worktree/` (engine, finish, resolve), the verify lock between children,
`host.py` and `claude --bg`, `watch.py`, respawn by job id, purge of transcripts on disk, `--add-dir`, and the
missing `bash-other-worktree` guard. Lineage, the card rules, check, accept, the states, the story rows and the
brief survive almost unchanged.

## 6. What would be new code

| Piece | What it does |
|---|---|
| `utils/orchestra/refs.py` | read and write the harness refs: fetch, push, one blob, no merge |
| `utils/orchestra/card.py` | the card, the grant, the brief; no card plan waiting in the ledger |
| `utils/orchestra/crew.py` | the single writer of crew state, as spec 05, plus the crew blob |
| `utils/orchestra/receipt.py` | write the receipt in the child; read and judge it in the parent |
| `utils/orchestra/check.py` | fetch the branch, count the AC, rerun the tests in a clean checkout |
| `utils/orchestra/accept.py` | merge, run the suite, close in one transaction |
| `utils/orchestra/resume.py` | rebuild a parent from the crew blob |
| `mcp/actions/orchestra*.py` | spawn, adopt, take, handback, ask, answer, check, reject, accept, land, digest, status, resume, release, forget, remove |
| hooks | refuse `AskUserQuestion` in a child; refuse a child merging or leaving its branch |

`spawn` is the one action that cannot finish its own job: it prepares everything and ends with the brief and the
order "open the child with `create_session`, then give its session id back with `orchestra adopt`". The harness
counts the child as running only when the session id comes back, so a failed `create_session` leaves no ghost.

## 7. What the harness must refuse

| Refusal | Why |
|---|---|
| a child calling `AskUserQuestion` | nobody is at the keyboard; it would wait forever |
| a child merging, pushing another branch, or writing the crew or a card ref | only the parent merges; those refs are the parent's |
| `accept` with no receipt, a stale receipt, or uncommitted files named in it | the proof must match the code |
| `accept` on a green the parent did not see itself | the parent reruns the tests |
| `spawn` without the open delegated plan, the name in the grant, or above the cap | the user approved a fixed crew |
| a child presenting a plan outside the grant's units | the grant is the approval |
| a second delegated plan while one runs | spec 05, unchanged |
| a child closing the parent's plan, or the parent closing while a child runs | the closing order of spec 05 |

## 8. Not proven yet

Each of these must be tried live before anything is built on it:

- pushing and fetching `refs/harness/*` through this cloud connection (pushing branches works; a custom ref is
  untested and may be refused);
- `create_session` with a brief as the first prompt, in an environment whose setup script installs the harness, so
  the child is governed from its first word;
- `send_message` both ways between two cloud sessions, and whether a message reliably wakes an idle parent;
- a child session's permission mode: never the plan mode, which stalls on an approval nobody can give;
- how long an idle child session survives, and what the parent sees when it does not;
- the cost of one child, measured, before the cap of three is defended.

## 9. Option B: children as subagents

Kept as the fallback, and worth building first if the user wants spec 05's shape without the cloud work:

- a child is an `Agent` call in the parent's session; one ledger, one disk, worktrees as spec 05 describes;
- the harness tells children apart by `agent_id` and `agent_type` in every hook payload, and by the SubagentStart /
  SubagentStop events, so the ticket, the card plan and the behaviours work as in spec 05;
- `spawn` becomes "the parent calls `Agent` with the brief"; no sessions port, no `claude --bg`;
- what is lost: nothing survives the parent's machine, and a subagent lives and dies inside the parent's session.

Most of B's code is also A's code (card, crew, check, accept, the story rows); only the transport differs. So B
first and A second is a real order, not wasted work.

## 10. What the user decides

1. **A, B, or B first and then A?** The recommendation is A, with the shared pieces built so that B is a cheap extra.
2. **May the harness keep a ref namespace on the remote** (`refs/harness/orchestra/*`)? If nothing of the harness may
   touch the user's remote, the card and the crew travel only in the brief and in messages, and a dead parent cannot
   be resumed.
3. **May a child push its own branch after every step?** Without it, a dead child loses its work.
4. **The cap:** three children, or fewer while the cost of one is unknown.
5. **Spec 05 for the PC:** still to be built as written (worktrees, `claude --bg`), or set aside for the cloud path?
