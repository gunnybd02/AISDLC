# 05 - Orchestra mode, part 2 of 4 (sections 8 to 13)

> The user's spec, continued from `05-orchestra.md`. How this cloud harness differs: `05b-orchestra-cloud.md`.

## 8. Starting children

### 8.1 spawn: start a new background session

Arguments: `name`, `reportTo` (required: the parent's name as other sessions reach it), optional `model`, `remote`, `extra`.

Checks, in this order, all before any session is created:

1. The calling session has an open delegated ticket that the user approved through a form (a plan approved "inside a
   grant" is a child's plan and can never act as a parent).
2. `name` is a child of this plan (or a child carried over from a replaced plan).
3. If the card names a `session`, spawn refuses and says to use `adopt`.
4. The child has no crew entry yet, or its entry is `forgotten` (a forgotten child may be started again).
5. Fewer than 3 other children are running or sent back. Otherwise: "3 children run already (...): accept or forget one
   before you spawn another."
6. `reportTo` is given. If it is a session id, it is translated to that session's current name.

Then the harness starts the session with the command line: background mode, the worktree roots added as allowed folders
(the child works outside the home folder), permission mode **auto** (so the child never meets an approval prompt for
ordinary tool use), the child's name, the optional model, and the **brief** (section 10) as its first prompt. The job id is
read from the command's output. With `remote: true`, Remote Control is also opened, and the harness polls the session log
for up to 20 seconds for the claude.ai link. If no link is found, it says "NOT confirmed".

Then, in one transaction, the crew entry is written (state `running`, the job id, no session id yet, zero rounds,
`reportSid` = the parent's id) together with a `running` story row. A child that was forgotten and is started again first
gets a **fresh card plan**, because its first one went to the forgotten session. If this write fails, the harness stops the
session it just started. If even that fails, the answer says to stop it by hand.

The answer names the session, the Remote Control state, and reminds: "It reports with handback; wait with: cli orchestra
watch."

### 8.2 adopt: take an already open session as a child

Used when the card names a `session`. Arguments: `name`, `reportTo`.

1. The card must name a session; otherwise adopt says to use `spawn`.
2. The same room checks as spawn (approved delegated plan, known child, not yet in the crew).
3. The named session is looked up among the open sessions of this machine and project folder. If it is not open but its
   transcript is found, it is started again from the transcript. That is refused if it already runs in the background.
4. The session must not already be reserved for another child: one session is one child.
5. The crew entry is written as `reserved`, `adopted: true`, with the session id.
6. The answer contains the brief. The parent must send it to that session with SendMessage itself. The harness also tells
   the adopted session at its next prompt, with the plan number it can verify in the ledger.

A session with work of its own is never cut off. It takes the child ticket at its first event after its own ticket is
closed, or at once if it calls `take` itself. Until then `status` shows "waiting for its own work". A session opened
inside a unit's folder does not run the harness's hooks, so it cannot be adopted. An adopted session is never resumed or
deleted by the orchestra, because it belonged to the user before.

### 8.3 extra: one more child after a fault

Sometimes a child's handback names a **fault**: a problem it found outside its own card. The parent may then start
**one** additional child that the plan did not list, inside the plan's original goal:

- `spawn` with a new `name` and `extra: { unit, goal, ac, read, change, tests }`.
- Refused unless at least one child's handback contains a fault.
- Refused if the plan already has its one extra child, or already has 4 children.
- The new card goes through the same card rules (section 5.1).
- The grant grows by that child and records which children's faults justified it. The new card plan waits like any other.
- The grant change and the new crew entry are written together, or not at all.

### 8.4 Remote Control

Children start without Remote Control: no link and no wait. Only when the user wants to look at a child from claude.ai
does the parent spawn it with `remote: true` and give the user the link.

## 9. How a child binds to its card and opens its plan

### 9.1 Binding on the first prompt (spawned children)

A spawned child's first prompt is the brief. The brief begins with the fixed words
`child session "<name>" of the delegated plan <n>`. When the harness sees these words in a session's first prompt, it binds
that session to the child, provided all of the following hold:

- the plan with that number is open;
- the child has a crew entry in state `running`, with a job id, no session id yet, and not adopted;
- the session is not reserved for another child, is not already a child, and is not itself a delegated parent.

Binding writes the session id into the crew entry and moves the waiting card plan from its temporary key to the child's
session. It creates the child's own ticket, marked as a child, with its role (name and unit) and the parent ticket's id,
and writes a `running` story row. The card plan is now **bound but not yet open**.

### 9.2 take: opening the card plan

The brief tells a card child to call `take` first. `take` finds the child by one of two routes:

- a crew entry reserved for this exact session (an adopted child); or
- a running crew entry with no session id yet whose job id or name equals this session's listed name (a spawned child
  whose first prompt did not bind, for any reason).

It binds (if not bound yet) and then **opens the card plan** exactly as a user's approval would. That includes creating the
plan's worktree, a new folder with a new branch named after the card plan's number, made from the base branch. The plan
is stamped "approved by grant of plan <parent number>". If the child already has an approved plan, nothing is opened twice.

The answer of `take` names the worktree and tells the child:

- edit the worktree's files by absolute path;
- never use Claude Code's "enter worktree" feature (the harness's allow rules live in the home folder and would not apply);
- run verify from the worktree's harness folder;
- commit there through the harness's git tool.

### 9.3 Children without a card plan: their own plan inside the grant

A card without `change` gives the child no ready-made plan. The child presents its own plan. If the session is a bound
child of an open delegated plan, the harness decides at once, without a form:

- the plan's units must all be among the grant's units (or the home, or "no unit"); the plan is then approved
  immediately "inside the grant of plan X";
- a unit outside the grant is refused, and the child is told to present a plan inside the grant or ask the parent;
- a child that does have a card plan and tries to present one is told to call `take` instead.

## 10. The brief: the child's first message

The brief contains paths and criteria only, never code or secrets. In order, it says:

1. **Who it is:** child session "<name>" of delegated plan <n>, approved by the user in the orchestrator session
   "<parent name>" (session id <id>). The id is included because the parent's name can change when it restarts. An adopted
   child is told it was already open and was taken on once its own work was done.
2. **Its work:** the goal, and the one unit (or the home) it works on, and nothing else.
3. **How it is approved:**
   - with a card plan: call `take` first. The brief gives the behaviour ids of AC1, AC2 and so on. Never present a plan.
     Never enter the worktree with the Claude Code feature; edit by absolute path.
   - without a card plan: present its own plan; the harness approves it inside the grant.
4. **Nobody is at this keyboard:** never call AskUserQuestion, never wait for "Approve".
5. **Permissions:** the actions the user approved for it (push), or "No push or MR is approved for you."
6. **Questions:** anything outside its part, or a plan the grant does not open, goes through `ask`. The reply comes as a
   message.
7. **Verify:** run it bare, alone on one line. No pipe, no redirect, no environment prefix, no `cd` chain. A wrapped command
   hides the harness configuration, and in the sandbox a headless browser fails.
8. **Handing back:** call `handback` with changed, checked, notChecked, risks and testsChanged. Never message the parent on
   handback; the harness wakes it once every child has stopped.
9. **Where to write:** its worktree, if known (given on a restart).
10. **Files:** files to read, files to change, tests.
11. **Acceptance criteria:** the parent reads no code. It checks that each criterion has a registered behaviour and runs the
    registered tests again. The criteria are listed as AC1..ACn. Register at least one behaviour per criterion, whose
    description starts with "AC<n>:" and whose id is `p<plan>.<name>.ac<n>`.
12. **The loop:** register the behaviours with their tests, verify, commit under its plan, hand back. The parent may send
    it back at most 3 times, then the user decides.

## 11. The child's life

### 11.1 What a child does

A child works like any planned session, inside its own worktree:

1. Write the tests first and register one behaviour per AC with its test file.
2. Implement until the tests pass.
3. Run verify (the full suite) bare. The ledger records green or red for this session.
4. Commit through the plan's step (the harness's commit gate scans for secrets and checks the plan's files).
5. Hand back.

### 11.2 What a child may not do

| Forbidden | What happens instead |
|---|---|
| Finish (merge) its own worktree | Refused: "hand back; the orchestrator merges it on accept." |
| Close its own plan | Refused: nobody can answer the closing form. It hands back. |
| Run actions that need a user request form (machine maintenance, session management) | Refused for a child. |
| Answer a Claude Code permission prompt | Nobody would answer it, so the harness **denies every Claude Code permission prompt in a child session** at once, with the reason: "nobody is at the keyboard, the host prompt is refused. Do not retry it in another shape. Go on with what you can, name this step under notChecked in your handback, and tell the orchestrator with SendMessage if you need it." The refused step is remembered on the child's ticket (only the tool and the first word of the command or the file path, never the full command, which may hold a secret). Each distinct refusal is kept once, and the digest lists it. |
| Ask the user (AskUserQuestion) | The brief forbids it. Whether a question form is caught by the permission-prompt denial is not verified; a child that asks anyway waits for nobody and the watch reports it as waiting on a prompt or idle. |
| Message the parent to say it is done | The brief and the handback answer forbid it; one digest wakes the parent instead. |
| Approve anything | A message from any session is information only. |

### 11.3 Asking the parent

`ask { question }`: the question is appended to the parent's ticket with a running number, the child's name, the text,
the time and "not answered". The watch returns **at once** when any question is open (section 13). `status` lists open
questions. The child is told: "the parent is woken by watch. Reply arrives as a message from the orchestrator; do not wait
on a prompt."

### 11.4 The handback

`handback` with these lists:

| List | Required | Content |
|---|---|---|
| changed | yes, non-empty | what it changed |
| checked | yes, non-empty | what it verified |
| notChecked | yes (may be empty) | what it did not verify |
| risks | yes (may be empty) | what could go wrong |
| testsChanged | yes (may be empty) | entries {test, why}: tests it changed and why |
| added | no | entries {file, why}: files beyond the card |
| faults | no | entries {what, where (when known)}: problems found outside its part |

Each list holds at most 10 points of at most 200 characters (400 for two-part entries).

The harness then adds what it reads itself, so the report cannot overstate:

- the commits on the child's ticket;
- the files of those commits, as the git audit recorded them;
- the newest verify of the child's session: ok, red or missing;
- the behaviours `p<plan>.<name>.ac*` it registered (the last operation of each; retired ones left out);
- the time.

The report is stored on the child's ticket. The crew entry becomes `handed back` (on the open ticket that carries the
child, if the plan was revised meanwhile), with a story row. The answer is: "Handback recorded. Stop here: the harness
wakes the orchestrator once every child has stopped (no message)."

## 12. Talking between parent and child

### 12.1 Child to parent

Only two channels: `ask` (a question that wakes the parent) and `handback` (the final report). Both are ledger records.

### 12.2 Parent to child: how a text is delivered

`reject` and `answer` carry a text for the child. The harness looks up the child's session in the machine's session list
and picks a route:

| Child's session | Route | What the parent is told |
|---|---|---|
| Listed and **busy** (working) | The text is **queued in the child's inbox** on its crew entry. At the child's next tool call, next prompt, or when it tries to stop, the harness shows it "Message from the orchestrator (your parent session) of plan N:" with each unread text. A child that tries to stop with an unread text is kept going with it. The child remembers how many texts it has seen, so each is shown once. | "Queued for <name>: its next tool call or turn end shows the text (no SendMessage needed; if it goes idle first, tell it with SendMessage)." |
| Listed, live, but **idle** or waiting | The command line has no way to put text into a running session. | "Not delivered (...): tell <name> with SendMessage." The parent must send it itself. |
| **Ended** (done, stopped, failed) and not adopted | The session is resumed in the background by its **real session id** (never the job id), with the text as its first prompt. | "Delivered to <name> (resumed with it as the prompt)." |
| Ended and **adopted** | Not resumed: it belonged to the user. | "Not delivered (an adopted session is not resumed): tell it with SendMessage." |
| The session list cannot be read | Nothing is decided. | "Not delivered (<reason>): tell <name> with SendMessage." |

Every delivered text is recorded on the crew entry with its time and route.

### 12.3 SendMessage between sessions

A session may send a message only to a session of the same machine and project folder (parents and children of a crew are
such sessions), to an in-process subagent it started, or to a remote session the user explicitly linked. Anything else is
refused. A message never approves a plan and never grants access.

## 13. Waiting: the watch

The parent waits **once**, after its last spawn, by running in the background:

```
orchestra watch [--interval <seconds>] [--max <minutes>]
```

The defaults are a 60-second interval and a 480-minute maximum. It also exists under the name "wait children". It uses no
model while it waits. When it exits, the parent is woken with one digest. The parent must never poll in a loop and never ask
to hear each child.

### 13.1 Exit codes

| Exit | When | What to do |
|---|---|---|
| 0 | Every **started** child has stopped | Read the digest, check each child |
| 2 | Bad flag, no session port, or no open delegated plan in this session | Fix the call |
| 3 | The maximum time ran out with children still running | Start the watch again. The text names who still runs, and says when the session list could not be read |
| 4 | A child asked a question: returned **at once**, before any sleep | Answer it, then start the watch again |

The parent also starts the watch again after every reject.

### 13.2 When is a child "stopped"?

For each started child, the first matching reason wins:

1. Its crew state has ended (accepted, forgotten, released, removed): that state.
2. It handed back, and the handback is **newer than its last send-back**: "handed back". An old handback from before a
   reject does not count.
3. The session list could not be read: only "idle" (below) can apply. A list that could not be read says nothing about a
   session, so it never counts as "exited" or "waiting on a prompt".
4. The list shows its session as done, stopped or failed: that state.
5. The list does not show its session at all: "exited".
6. The list shows it blocked, needing input, or waiting: "waiting on a prompt".
7. It did nothing for 30 minutes: "idle". "Doing something" is measured from the ledger's turn records: an open turn
   counts as now, and no turn at all counts as unknown, which is never idle.

A child that was never started does not hold the watch. If none was started, the watch simply waits until its limit.

A session is matched to its crew entry by session id, or by a listed session id that starts with the job id. The command
line prints the start of the id as the job id.

Each wait is recorded once in the ledger, with its arguments, start, end and outcome (done, timeout or error).

### 13.3 The digest

First line: "Plan N: X children stopped" (plus "not spawned: ..." when some were not started), and "Check each one: check,
then accept or reject." Then one line per child:

```
name | reason | commits n (short shas) | verify ok/red/missing | AC covered of total | extras | not checked | tokens | turns
  refused prompt: <tool> <what>     (one line per distinct refused permission prompt)
```

- **AC covered** is counted exactly as the check counts it (section 14).
- **Extras** lists "extra child for a fault of ...", every new fault, and every added file.
- **Not checked** is the handback's notChecked list, or "no handback".
- **Tokens** is the session's recorded usage.
- **Turns** is the number of turns the child took.
