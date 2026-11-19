# 05 - Orchestra mode, part 4 of 4 (section 22)

> The user's spec, continued from `05-orchestra-3.md`. How this cloud harness differs: `05b-orchestra-cloud.md`.
> Replaced in the cloud by `system.md` (PRs 61 to 81): 22.1 and 22.3 (inbox, SendMessage, resume: signed orders).

## 22. What went wrong before, and the rule each failure left

### 22.1 Failures met in the current harness

| What happened | Root cause | Rule now |
|---|---|---|
| Eight children ran the full suite at once and killed the machine | No shared test lock, no cap | One verify at a time per repository; at most 3 running children |
| A child could not edit, verify or commit inside its card | The card plan was moved to the child but never opened | `take` opens the card plan like a user approval, in its own worktree, stamped as approved by the grant |
| A child in its worktree hit permission prompts; a forgotten child could not restart | The home's allow rules do not reach another folder | Children start in auto permission mode with the worktree roots allowed; a forgotten name gets a fresh card plan |
| A failed session listing marked every child "exited"; adopt could resume a live session | An unreadable list was treated as an empty one | An unreadable list is an error, never empty; the watch then counts only idleness |
| Check found no AC after a revision | The parent was renumbered, the card ids were not | Checks read the card plan's own number |
| Remove could delete a session under its work | No state filter | Only children that no longer run are removable |
| A child's plan stayed open after accept or forget | The child's session stops; nothing ended its plan | Ending a child ends its plan in the same call; its worktree is given up |
| Purge took children that were still working or still listed | Matching by id prefix only | Never a child of an open plan; never any listed session |
| Reject and answer texts never reached the child | No delivery path; resume used the job id | Delivery by route (inbox, SendMessage, resume by real session id); briefs name the parent by id; `land` for stopped children |
| Carried children lost their card and ticket after a new plan | Lineage was not read | Cards and tickets are looked up through the lineage chain; another plan is refused while a delegated plan runs |
| Status of an old plan number failed; the close form counted other plans' children | Revisions renumber; lineage read every superseded ticket | Only the plan's own chain; old numbers resolve to the plan they became |
| Two children hung "blocked" at start with no job; respawn said "running" | Blocked was taken as alive | Blocked with no job counts as orphaned and can be respawned (not yet proven in a live run) |
| A delegated parent never closed itself | Uncovered files ignored the parent's own step; the commit stopped at "deliver" | The parent in "deliver" has nothing left; the commit closes a delegated parent once every child has ended |
| Every child commit was refused after plan tiers were added | Card plans were opened without the pipeline profile | Card plans open with the same profile as any plan |
| A child's verify upgraded the live ledger | Tests ran against the live database | Verify and merge tests run against a copy of the ledger |
| A busy child never saw a reject or answer | The command line cannot inject text into a running session | Texts for a busy child are queued in its inbox and shown by its own hooks |
| A child froze on a Claude Code permission prompt | Nobody answers it | Every permission prompt in a child is denied with a "go on" reason and listed in the digest |

### 22.2 Classes of failure from the earlier harness, still guarded

| Failure class | Guard |
|---|---|
| A refused spawn left a session running | Every refusal comes before the session starts; a failed save stops the session |
| A child wrote into the parent's worktree (it took the parent's plan number for its own) | The brief names the parent's plan as the parent's; take names the child's own worktree |
| An AC like "works" passed review | Filler-word rule: at least 2 content words |
| A check was green on uncommitted work | Dirty files fail check and land; accept merges commits only |
| Behaviour ids collided across plans | Ids carry the plan number and the child name |
| A handback older than a send-back ended the watch | The send-back time is compared |
| A merge busy on another session's lock was blamed on the child | "Busy" says retry, do not send back |
| Removing children asked three forms | One checklist; one-use passes spent only by a removal that ran |
| A note from each child woke the parent repeatedly | Children never message on handback; one digest |
| A child edited a user-only file through a shell script | Text guards can be bypassed by scripts; such files need real write guards |
| A shell wait ran inside the sandbox and saw no sessions | A session list that cannot really be read must say so, never return empty |

### 22.3 Open gaps (known, not fixed)

| Gap | Effect | Workaround |
|---|---|---|
| No code refuses AskUserQuestion in a child as such; only the brief forbids it | A child that asks waits for nobody | The watch shows it as waiting on a prompt or idle; answer or forget it |
| Text cannot reach a live but idle child | Reject or answer says "Not delivered" | The parent sends it with SendMessage |
| Uncovered files ignore the parent's own commits | The last accept before the parent's step says "waits" | Do the parent's step last, or first (section 16) |
| Accept merges with the published release's merge code but runs the child's own test suite | A new refusal added by the child can block its own accept | Make new gates additive (strip rather than refuse) |
| Check runs only the AC tests | A failure elsewhere shows up only at the merge test | Read the handback's not-checked list and risks |
| Respawning an orphaned child is not yet proven live | It may not come back | Forget it and hand the card to a new child |
| A child can write into another plan's worktree | The sandbox allows the whole worktree area; the old "other worktree" guard is not ported | Rely on the brief and the take answer naming its own worktree |
| A child stalled on an API error still shows "running" | It holds the watch until 30 minutes idle or the maximum | Use a shorter `--max`; respawn or forget |
| A parent plan with no behaviour of its own cannot widen itself by one file | Out-of-plan documents of a parent need a revision or a later plan | Name the parent's documents in the plan from the start |
| The 4-children limit is not enforced at presentation | A plan with more children is accepted | Follow the skill rule |
| The skill says the parent's own commit is refused while a child is open; no gate does that | The skill and the code disagree | Commit the parent's step after the last accept anyway |

### 22.4 Lessons for anyone building such a mode

- Test every action through the real wiring (the real tool call, the real hook), not through hand-built fakes. Every live
  failure of the earlier harness had passed a unit test with a full fake database.
- An action with a side effect outside the database (a session, a worktree, a branch) must state every refusal first.
- A check proves only the tests the child wrote. Read what the child says it did not check.
- Key anything durable by something that survives revisions (a draft id, the card plan number, the lineage chain).
- Never present another plan while a delegated plan runs: revise it.
- Read the host tool's documentation before relying on a sandbox or command-line behaviour (directory switches, pipes,
  sending text to a session). Several designs were built on assumed behaviour that the tool did not have.
