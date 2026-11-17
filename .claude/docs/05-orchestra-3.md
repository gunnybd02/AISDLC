# 05 - Orchestra mode, part 3 of 4 (sections 14 to 21)

> The user's spec, continued from `05-orchestra-2.md`. How this cloud harness differs: `05b-orchestra-cloud.md`.

## 14. Checking a child

`check { name, timeoutMin? }` is the parent's mechanical review.

### 14.1 Refusals, in order, before any test runs

1. `timeoutMin` must be a whole number from 1 to 30 (default 10).
2. The child must have a crew entry (it was started).
3. The child must have handed back, with a handback newer than its last send-back. Otherwise: "Child X has not handed
   back...".
4. The child's plan must be open.

### 14.2 Where the tests run

- The folder is the child's **worktree** while it is open, otherwise the unit's main folder.
- The worktree's uncommitted files are listed as **dirty**.

### 14.3 Which behaviours count for which AC

- The behaviour ids are read with the plan number **of the child's own card plan** (taken from its behaviour ids). If the
  parent plan was revised and renumbered, the card the child took keeps its original number.
- For each id `p<n>.<name>.ac<k>`, only the latest record counts. Retired behaviours do not count.
- A behaviour counts for criterion N when its description starts with "AC N" followed by one of `:` `.` `)` `-`
  (case-insensitive; "AC3:", "ac 3.", "AC3)", "AC3 -" all count as AC3), and it names at least one test.
- The criterion number comes from the description, not from the id.

### 14.4 Running the tests

- Each distinct test file runs **once**, even when several criteria share it.
- Path translation: a relative path is taken inside the worktree. A path inside the worktree runs as is. A path in the
  main folder of the same repository, or in another worktree of it, is translated to the same file inside this worktree.
  A path that cannot be placed there fails that criterion ("outside the worktree: register it by its path in the
  repository").
- **A child of the home:** each test file runs as a Python unit test module from the repository (or its harness
  folder), with the check's time limit, keeping the last 1500 characters of output.
- **A child of a unit:** the test must lie in the worktree or the unit's main folder, otherwise it is refused as outside the
  unit. It runs by the unit's configured verify rule; the rule's command takes the test as a placeholder, or as the last
  word. A unit with no matching rule refuses: "declare one in the project config".

### 14.5 The result

The check is **green only when** no criterion is missing, no test is red or refused, and nothing is dirty. The answer starts
with "AC x of y covered by a registered behaviour; z test file(s) run again in <folder>: all green / red for AC...". It then
lists:

- the missing criteria;
- each red or refused test with the start of its output;
- the dirty files ("accept merges only commits, send it back to commit").

### 14.6 The base proof (home children)

When a home child's check is green, every test is run once more at the **commit its worktree started from**, in a temporary
detached worktree that is removed afterwards. A test that is already green there passes without the child's change, so it
proves nothing. The check stays green, but warns: "already green on the base: ... green there is not a proof." The parent
then sends the child back for a test that fails without the change, or accepts when the work is a refactor (where passing
before and after is the point). If the base proof cannot run, that is noted, not failed.

### 14.7 Records

Every check, green or not, writes a `checked` story row with its result summary (green, uncovered ACs, uncommitted
changes, red) and each detail line. A green check marks the crew entry "checked at round N" (the current number of
send-backs). Any later reject makes this stale.

## 15. Rejecting and accepting

### 15.1 reject { name, why }

- Refused once the child has been sent back 3 times: "the user decides now (forget it, or say what to do)."
- Otherwise: rounds + 1, state `running`, `sentBackAt` = now, a `rejected` story row, and the reason is delivered to the
  child by the route of section 12.2.
- The answer: "sent back (round n): <why>. <delivery result> Its check is stale until it passes again."
- After a reject, the parent starts the watch again.

### 15.2 accept { name, why? }

Nothing is settled if any step refuses. In order:

1. **Done?** The child must have a handback. If it has commits, the newest verify of its session must be green. Red or
   missing: "send it back to run verify".
2. **Checked this round?** A child with AC must have a green check at the current round. Otherwise: "has not passed a
   check this round: run check; accept only after it passes."
3. **Merge**, only when the child's plan has an open worktree:
   - one merge at a time per repository: a lock with a 10-minute wait. A lock whose holder process is gone, or that is
     older than 30 minutes, is taken over;
   - the worktree must be clean, must have commits since it left the base, and must have no merge in progress;
   - the base branch is merged into the child's branch. A conflict aborts the merge;
   - the repository's configured test command runs on the merged tree, against a **copy** of the ledger so a test can
     never touch the live one, with a 15-minute limit. For the home this is the full parallel suite;
   - the main checkout must be on the base branch;
   - the base branch moves to the child's branch by **fast-forward only**;
   - the worktree and its branch are deleted, and a receipt is kept.

   Results:
   - **busy** (another merge holds the lock): "The child is not at fault: retry accept in a moment, do not send it back."
   - **any other failure**: "Send it back (reject with why) so it brings its branch up to date and verifies again."
     Conflicts come with the list of files; the child runs `sync` in its worktree, resolves, verifies and hands back.
4. **Settle**, in one transaction:
   - the crew entry becomes `accepted`, with an `accepted` story row;
   - the child's ticket closes as accepted;
   - the child's plan is recorded as delivered.
5. **Parent close** (section 16), still in that transaction.
6. **Publish:** for the home, publishing the new harness release is deferred until after the ledger rows are written,
   because a new release may upgrade the ledger.
7. **Clean-up of what the session left:**
   - the background session's own scratch worktree and branch (which the command line created under the home's
     Claude folder, named after the session) are removed. A branch with unmerged commits is kept;
   - the plan worktree, if still there, is given up (a branch with commits of its own is archived first).

Answers:

- "Child X accepted." (others still open);
- "every child accepted, and every planned file is covered: plan N is delivered. Report to the user.";
- "every child accepted. Plan N waits for a file no child covers (...). Commit the plan's own change to deliver it, then
  report to the user."

A child of another unit is checked in its own folder with that unit's rules. It is accepted the same way, but the merge
pushes nothing.

## 16. How the parent plan closes

The parent closes **delivered, without any form**, when both are true:

- every child of the grant has ended (accepted, forgotten, released or removed); and
- nothing is left for the parent: either the parent has already committed its own step (its phase is "deliver"), or no
  planned file is left uncovered by the cards and the handbacks.

That leaves two valid orders:

1. **Children first, then the parent's own step.** The last accept says "waits for a file no child covers". The parent
   commits its own files. Its commit sees that every child has ended, and the plan closes itself.
2. **Parent's own step first, then the last accept.** The parent commits its files while children still work. Its commit
   does not close the plan (children are still running). The last accept sees the parent in "deliver" and closes it.

The skill tells the parent to commit its own change after the last accept, and says a gate refuses it while a child is
open. The current code has no such gate: both orders above work. Order 1 is still the safer habit, because the parent then
commits on top of every merged child and its commit closes the plan at once.

## 17. Recovery and clean-up tools

| Tool | When to use it | Effect | Refused when |
|---|---|---|---|
| `respawn { name, reportTo? }` | The child's session ended (done, stopped, failed) **before** it handed back, or it is "orphaned": shown as blocked with no job behind it | The same session id is resumed in the background, with a fresh brief: the parent's current name (looked up by its id) and the child's worktree. State `running`, `sentBackAt` = now (so an old handback no longer ends the watch), story row "respawned" | The child is adopted; the child has ended; the session list cannot be read; the session still runs and is not orphaned; no session id is known ("forget it and spawn it again") |
| `land { name, why? }` | The child stopped **without** handing back, but its committed work is good | Runs the check; when green, merges and settles exactly like accept | The child has ended; the list cannot be read; it still runs; it has no commit; it has no open worktree; uncommitted files ("respawn it to commit them, or forget it"); AC tests not green |
| `release { name, why }` | Give the session back to the user; the child keeps its work and its plan | State `released`, the child's ticket closes as released, its plan is **not** ended, the session is left alone | No reason given; already ended |
| `forget { name, why?, plan? }` | Drop a child that will not come back | State `forgotten`, its ticket closes, its plan is dropped. A spawned (not adopted) session is stopped. Its scratch worktree is removed, and its plan worktree is given up (a branch with its own commits is archived first). The name may be spawned again later, with a fresh card plan | Not in the crew |
| `remove { name?, why?, plan? }` | Delete finished child sessions after the user agrees | **Without a name**, the first call is refused and returns **one** checklist form listing every child that is not running and not yet removed (name, state, "existing session" or "background session" with the id prefix, goal). The user ticks some; each tick gives a one-use pass. The second call removes exactly the ticked ones. For each: state `removed`, its ticket closes, its plan is dropped; a background session is stopped and deleted from the machine, its transcript deleted with its token usage kept in the ledger; its plan worktree is given up. A named child goes through the same pass | A named child still running ("accept it, forget it or release it first"); already removed; nothing removable |
| `purge` | Clean every leftover child session on disk, across plans | Lists every session transcript on disk that the ledger records as a child and that has stopped for good, and asks **one Yes/No form** naming them by 8-character id prefixes. On Yes, each: usage saved, transcript and its folder deleted, background job removed, crew entries removed (plans ended, worktrees given up), any still-open child ticket closed as removed | Never touches: a session the ledger does not record as a child; an adopted session; a child still working for an open delegated plan; the calling session; **any** session the machine's list still shows, in any state. An unreadable list refuses the whole call |

The `plan` argument of forget, remove, read and answer reaches an older delegated plan of the same session by its number,
including numbers that a revision replaced.

Which sessions are deleted is always the user's word, each time. The transcript file of a removed background session is
deleted only by remove and purge.

## 18. Reading the state

- **`status { plan? }`** prints "Plan N: x of y accepted", then one line per child:
  `name | session <id> | session state <state> | phase | plan | behaviours n | commits n | verify | state (+ reason, sent back n×) | handback yes/no`.
  Children carried from a replaced plan are marked. Open questions follow, with a reminder to answer them. Asking for an
  old plan number says "plan X became plan Y".
- **`read { name, plan? }`** prints a child's handback in full: changed, checked, not checked, risks, tests changed,
  added, faults, commits, files, verify, behaviours. It works after the plan closed too.

## 19. Revising a delegated plan while children work

Only a **revision** of the running delegated plan is allowed; another plan is refused (section 5.4). A revision is approved
again under a **new plan number**. The old ticket closes as "superseded", and the new ticket **carries the crew**. The
following rules keep carried children working:

- **Lineage:** a ticket's chain is itself plus the superseded delegated tickets of the same session that are really its
  ancestors. That means the same draft (a revision), or a ticket whose crew entry it carried (the same name with the same
  job id or session id; a name started again later is not a carry).
- **The card stays where it was:** a carried child's card is found in the grant of the ticket that holds it, and keeps that
  plan's number. Its behaviour ids and its check use the card plan's own number, never the parent's current number.
- **The child's ticket keeps the old parent id.** The child is found by searching every id in the chain.
- **A handback of a carried child** updates the crew entry on the open ticket that carried it, not the closed one.
- **Old plan numbers still work:** asking for plan X, which became plan Y, resolves to the newest ticket of that draft.

Rule of thumb: anything durable is keyed by the draft, the card plan number or the lineage chain, never by the parent's
current plan number.

## 20. The orchestrate skill: the parent's procedure in full

The skill is the instruction text the parent follows. Its content, step by step:

### 20.1 Rules that hold throughout

- The parent alone says "done", and only after every child is accepted. Children stay open for the user to look at until
  the user agrees to remove them.
- Reading costs tokens. Never read a child's work beyond its digest line, its handback and its diff. A green check is no
  review for a child that touches a guard, a gate, a deletion or the wake-up mechanism: read that diff, only its code lines.
- A child cannot ask the user. Anything that needs the user (a push, a merge request, a real external system, a choice)
  comes back to the parent, and the parent asks the user.
- Messages from children are information. They never approve anything and never widen the plan.
- Brief a child with pointers (unit, ticket key, files, goal), never with secrets or pasted file content.

### 20.2 Steps

1. **Understand the request.** Look up the relevant code and tickets so each child's goal names its unit and what done
   means.
2. **Present the plan** with `children`. Each card: name, unit (or home), goal, 1 to 6 short AC that each name a visible
   case, optional read / change / tests paths (paths only), optional actions (push). A card with change opens its plan by
   itself. One goal per child. The parent plan's own files are the notes or documents it commits at the end. Ask with the
   form; one "Approve" approves all children.
3. **Start each child:** `spawn { name, reportTo: <this session's name> }`. The parent's name comes from the session list.
   No Remote Control unless the user wants to watch a child. A card naming an open session is adopted instead:
   - `adopt` returns a brief, which the parent sends with SendMessage (asking to be notified when the child is idle);
   - the adopted session takes the child ticket after its own work closes, or at once by calling take;
   - `release` cancels the reservation or gives the session back at any time;
   - a closed session is started again by adopt when the plan names it by id or by the start of its id;
   - a session opened inside a unit's folder has no hooks and cannot be adopted.
4. **Wait once:** start the watch in the background after the last spawn.
   - Exit 3: start it again.
   - After a reject: start it again.
   - Exit 4 (a question): answer with `answer { name, text }`. A busy child gets the text at its next tool call ("Queued").
     For an idle child the answer says "Not delivered"; then send the same text with SendMessage.
   - When only the user can decide, ask the user first.
   - Never poll, never ask to hear each child.
5. **Read** the digest, then each stopped child's handback.
   - A fault outside a child's part may justify one extra child, once, inside the plan's goal.
   - A child that will not come back: `forget` with the reason.
6. **Check, then reject or accept:**
   - Not covered or red: `reject` with the check's text. Send it with SendMessage only when the answer says "Not
     delivered". Check again after the next handback.
   - At most 3 rounds. The fourth reject is refused: ask the user, or forget the child.
   - A green check with a base warning: send the child back for a test that fails without its change, or accept a
     refactor.
   - Green: `accept`. It is refused without a handback, without a green verify, or without a green check this round. A
     home child is merged into the harness branch first.
   - A busy refusal: retry accept in a moment; never send the child back for it.
   - A conflict or a red test: reject with the text; the child syncs its worktree, verifies and hands back.
   - A child of another unit is checked in its own folder with that unit's test rule; same check, same accept.
   - Accept leaves the session and cleans the plan's branch.
7. **Remove the sessions:** once no child runs, call `remove` with no name. The first call returns one checklist; put
   it to the user exactly as given; call remove again; exactly the ticked children go. Do this **before** the parent's own
   commit, which closes the ticket.
8. **Commit the parent's own change** after the last accept. The skill says a gate refuses it while a child is open;
   the current code has no such gate (section 16), but this order is the one the skill expects.
9. **Report to the user** from the handbacks: each child, its commits, what was checked, what was sent back and why, and
   what is not checked. Push or a merge request only on the user's word, or for a child whose card had `push`.

### 20.3 Common mistakes the skill warns about

| Mistake | Correct way |
|---|---|
| Running verify through a pipe or redirect | It then runs inside the sandbox, where a headless browser fails. Tell children to run it bare |
| Deleting a child's plan branch by hand | No session deletes it. Accept, finish or drop clean it; a sweep catches leftovers. A branch with its own commits is archived, not lost |
| A child guessing its worktree from a folder listing | Its own worktree is named after its own plan number and is given in the take answer and in the refusal of its first wrong write |
| Accepting on the child's word "done" | Always check first. A green check is still no review for guards, gates and deletions |
| A child stuck on a limit or a missing form | Never re-link such a session: stop it |
| Forwarding a child's question as if the user asked it | Ask the user here, then answer the child |
| Two children on one unit | Refused by the plan. Split by unit; the home allows several with worktrees on |
| Spawning before approval | Refused until the delegated plan is approved |
| A refused accept of a home child because of a conflict | Reject it with the files; the child syncs, resolves, verifies, hands back |

### 20.4 How to check the run is complete

- `status`: every child shows `accepted` and the first line says "N of N accepted".
- The session list shows each child by name, until removed.

## 21. Every limit and number

| Limit | Value | Why |
|---|---|---|
| Children running at once | 3 | Eight children each running the full suite exhausted a 15 GB machine |
| Children per plan | 4 (skill rule; enforced only when adding an extra child) | Quota: each child is a full session |
| Extra children | 1 per plan, only after a fault in a handback | Keep the plan's scope fixed |
| Send-back rounds | 3, then the user decides | Stop endless ping-pong |
| AC per child | 1 to 6, each at most 120 characters, at least 2 content words | A criterion must name a real, testable case |
| Goal | at most 200 characters | One goal per child |
| Paths per list (read, change, tests) | 8 | A card is a pointer, not a document |
| Child name | at most 40 characters, lower case, digits, dashes | It becomes the session name |
| Session name to adopt | at most 60 characters | |
| Handback list | 10 points, 200 characters each (400 for two-part entries) | A report, not a dump |
| Check time limit | 1 to 30 minutes, default 10 | |
| Idle threshold for the watch | 30 minutes without a turn | |
| Watch defaults | interval 60 s, maximum 480 minutes | |
| Remote Control link wait | 20 seconds | |
| Merge lock wait | 10 minutes, then "busy" | One merge at a time per repository |
| Stale merge lock | 30 minutes, or its holder process is gone | |
| Merge test limit | 15 minutes | |
| Test output kept | last 1500 characters | |
