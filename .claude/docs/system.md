# The system: the target design

Agreed with the user on 2026-11-18. This is where the harness is going, not what is built today (that is
`handover.md`). Each later plan says which part of this it builds. It replaces `units` in `project.json` (PRs 31, 53)
and the note files of `05b-orchestra-cloud.md` section 2b as the way parent and child work together.

**In one sentence:** the user approves *what* once, children build *how* freely in any repository given by URL, the
repository's own CI and the harness check everything, and the user allows the result once.

## 1. Principles

1. **Only the user's forms approve.** Two per piece of work: form 1 (start) and form 2 (end).
2. **The repository describes itself.** Protected branches, CI pipeline, required checks and issues live in it.
3. **The plan carries the rest.** Repository URL, folders, tests, children, limits: all shown in form 1.
4. **The model calls, the harness decides.** No check rests on the model's word.
5. **Sessions never message upward.** A child talks through git and CI; the parent sends signed orders down.
6. **Everything is recorded by itself**, in each session's ledger; every ledger goes to one memory on Drive.

## 2. Who owns what (no project.json)

`project.json` and its reader `config.py` are removed.

| Owner | Holds |
|---|---|
| The repository | protected branches, CI pipeline, required checks, issues |
| The plan (form 1) | repository URL, base, folders (scope), test command, children, criteria, acceptance tests, limits (lower only) |
| The harness | the floor pipeline (base rules, banned words), the flow, defaults (3 children, 3 rounds), the forms |
| Drive | `tickets/` (proof of the user's approvals), `db/` (every ledger) |
| The machine's environment | the Drive folder id; on a PC, the path of the user's ledger |

| Was in project.json | Now |
|---|---|
| `name` | dropped |
| `verify` | the plan (local tests); the repository's CI is the gate |
| `protected` | read live from the forge; `main` and `master` always count |
| `banned` | a row of the floor pipeline; a plan may add more |
| `limits` | defaults in the harness; a plan may lower them, never raise them |
| `units` | the plan: repository URL, folder, base |
| `ledger` | an environment variable on the PC |

## 3. The four parts

| Part | Job |
|---|---|
| Sessions | start a child, send it a signed order, stop it, archive it; hosts: cloud and PC |
| Plan | parent: one delegated plan, form 1 to form 2; child: its own plan, approved inside its scope by the grant |
| DB | each session's ledger records itself; copies go to Drive `db/` and are joined into one memory by row id |
| MCP server | `find`, `guide`, `run`; plug-ins: the forge (GitHub, GitLab) and the tracker (issues, Jira) |

## 4. What a repository needs (the ready check, at plan time)

| Needed | When missing |
|---|---|
| the session can reach it (the user's account has access; public or private both work) | `add_repo`, approved by the user |
| a CI job that runs the harness's hard rules | the plan's first step adds the CI file |
| that job is a required check on the base branch | the user turns it on; form 1 says so |
| issues are on | the user turns them on |

Once per repository; then any plan needs only its URL.

## 5. The flow

```text
User              Parent              Drive             Repo+CI             Child
  |                  |                  |                  |                  |
== 1. Approve once =================================================================
  |                  | ready check      |                  |                  |
  |                  |------------------------------------>|                  |
  | form 1: repo, kids                  |                  |                  |
  |<-----------------|                  |                  |                  |
  | Approve          |                  |                  |                  |
  |----------------->|                  |                  |                  |
== 2. Set up =======================================================================
  |                  | tickets/ CSV     |                  |                  |
  |                  |----------------->|                  |                  |
  |                  | issues, plan branch, AC tests       |                  |
  |                  |------------------------------------>|                  |
  |                  | draft PR, watch  |                  |                  |
  |                  |------------------------------------>|                  |
  |                  | new session: #N  |                  |                  |
  |                  |.......................................................>|
== 3. Child works freely ===========================================================
  |                  |                  |                  | read issue #N    |
  |                  |                  |                  |<-----------------|
  |                  |                  | read ticket row  |                  |
  |                  |                  |<------------------------------------|
  |                  |                  |                  |                  | (harness: match?)
  |                  |                  |                  |                  | (own plan, in scope)
  |                  |                  |                  | commit #N, push  |
  |                  |                  |                  |<-----------------|
  |                  | CI event (doorbell)                 |                  |
  |                  |<....................................|                  |
== 4. Check ========================================================================
  |                  | (run AC tests)   |                  |                  |
==    red ==========================================================================
  |                  | order: fix (signed)                 |                  |
  |                  |------------------------------------------------------->|
  |                  |                  |                  | fix, push        |
  |                  |                  |                  |<-----------------|
==    green ========================================================================
  |                  | merge to plan branch                |                  |
  |                  |------------------------------------>|                  |
== 5. End ==========================================================================
  |                  | order: stop (signed)                |                  |
  |                  |------------------------------------------------------->|
  |                  |                  | db/ ledger copy  |                  |
  |                  |                  |<------------------------------------|
  | form 2: merge+delete                |                  |                  |
  |<.................|                  |                  |                  |
  | Allow            |                  |                  |                  |
  |----------------->|                  |                  |                  |
  |                  | plan branch -> base                 |                  |
  |                  |------------------------------------>|                  |
  |                  | archive          |                  |                  |
  |                  |.......................................................>|
  |                  | db/ own copy     |                  |                  |
  |                  |----------------->|                  |                  |
```

`--->` a call or a write; `...>` a session started, archived, or a form shown; `(text)` work inside one session.

## 6. The pieces of work

**Form 1** shows: the repository URL, base and plan branch; the ready check; the test command and limits; per
child its scope, steps in words, criteria, and its acceptance test files.

**The acceptance tests** are written by the parent before any child starts, pushed on the plan branch, and locked:
no child may change them (its harness and CI refuse it). A child's job is to make them pass.

**Issue #N**, opened by the parent's harness in one format, `harness-issue/1` (`utils/orchestra/issues.py`):

| Part | Holds |
|---|---|
| title | `[p<plan>] <name>: <goal>` |
| sections, in order | Goal, Acceptance criteria, Scope, Tests, Locked acceptance tests, Branch, Commits |
| machine block | `{format, plan, planSha, child, repo, path, branch, start, scope, tests, acTests}` and its sha256 |

**The registration** (`.harness/register/<name>.json`, format `harness-register/1`): the issue, its block's hash, the
ticket file's hash and the plan's hash. The child's harness writes it at `take`, after the issue and the ticket row
match, as the first commit of the branch (`#N <name>: register (...)`), and pushes it. The ledger keeps it as a row,
and the card plan's approval names its commit.

**The commit format**: every commit on a child's branch starts `#N <name>: `, written by the harness (steps, questions,
handback, the parent's send-backs and answers).

**The ticket CSV**, `tickets/<plan>__<sha>.csv` on Drive, one row per child, written by the harness at form 1 (the
model only uploads it by reference):

| key | plan sha | child | repo | issue | issue sha | branch | scope | AC tests | approved at |
|---|---|---|---|---|---|---|---|---|---|
| `41_issue_api` | `0ada55...` | api | github.com/acme/shop | #41 | `9f2c...` | `orch/p7/api` | `api/src/orders/;api/src/routes/` | `.../order_history.py` | 2026-11-18T... |

**The child's own plan**: its exact files, steps and tests; every commit names #N; approved by the parent's grant
only inside the scope.

**`harness ci`** (`python3 anchor.py cli ci --base <plan branch> --head <child branch>`, `utils/orchestra/ci.py`): the
child's gate run again on the forge, from the branch and its issue alone (no session, no ledger). Rules: branch, base,
issue, registered (first), subjects, marks, secrets, scope, locked. One line per rule; exit 1 when one fails; a rule
that cannot run fails as "not checked".

**The CI workflow** (`.github/workflows/harness-ci.yml`, `utils/orchestra/workflow.py`): a GitHub Actions file in the
plan's repository, written by `lock` on the plan branch with the acceptance tests and locked like them. On each push of
a child (`orch/p<n>/<name>`) to a pull request into `plan/p<n>` it gets the harness at one pinned commit (public: no
secret), runs `harness ci` with a read-only token, then the child's unit test command in its folder. The rules come from
the pinned harness, never from the child's branch. The user may make the job `harness-ci` a required check.

## 7. The gates (one rule set, three runners)

| Gate | Where | Checks |
|---|---|---|
| Child's harness | the child's machine | issue, ticket row and hashes match before any work; files only in scope; commits name #N; no secret or AI mark; locked tests untouched |
| CI (`harness ci` + the repository's own pipeline) | the forge, out of the child's reach | the same rules again; the repository's tests; branch and issue link; PR into the plan branch |
| Parent | the parent's machine | runs only the acceptance tests; never reads the code |

The rules have one owner: the rows of the floor pipeline. CI runs the same rows as `harness ci`.

## 8. How sessions talk

| Direction | How |
|---|---|
| Child to parent | a push; CI runs; the CI event wakes the parent that watches the PR (the doorbell) |
| Parent to child | a signed order by `send_message`: `fix`, `answer` or `stop` |
| Content | a question and the receipt are commits on the child's branch; PR comments are only a readable log |
| Safety net | one timer check-in (about 50 minutes, then about every 4 hours), for a child that dies silently |

**An order:** `orch <plan> | child <name> | issue #N <sha> | round <n> | kind <k> | mac <hmac>`. The child's
harness checks it where it arrives (the notifications answer): the sender is the parent's cloud session id given in
the brief, plan and issue match, the round is the next one and at most 3, the mac is right (a key per child, made at
spawn). A valid order unlocks one action (`resume` for a fix, going on for an answer, `stop`); an invalid one
unlocks nothing. No order widens the scope, touches the locked tests or approves anything.

## 9. Memory

- Each session's ledger records by itself: prompts, turns with their plan, calls, gates, commits, verify receipts,
  the issue a child registered, orders, CI events.
- Drive `db/` gets each child's copy when it stops and the parent's at the end; they are joined into one memory.
- The trace: form 1, ticket row, issue #N, branch, commits "#N", CI runs, parent's check, merge, form 2; a ledger row
  at every step.

## 10. Forms the user answers

| Form | When |
|---|---|
| Form 1: approve the plan | start |
| Form 2: merge the plan branch into the base and delete the children | end |
| Only when needed | a 4th send-back round; `add_repo`; turning on a repository setting |

## 11. The harness repository is one repository

The same model applies. Its one difference: a merge into its `main` goes live in every session (publish on merge,
with the fallback, PR 57). The plan branch and form 2 are what guard that.

## 12. Live facts this rests on

Probe of 2026-11-18 (draft PR 59, child session `session_01EXL6xZRuaNnqoVipxBhukR`):

| Question | Answer |
|---|---|
| Can a session push a CI workflow file? | yes |
| Does a CI result wake the session that watches the PR? | yes, within seconds |
| Does a child's PR comment wake it? | no: three comments, no event |
| Can a parent message a child it started? | yes, in about 2 seconds; the child acted on it |
| How does the message arrive? | through notifications, inside a tool answer, not as a prompt, even when the child was idle |
| What is `from-session`? | the parent's cloud session id (`session_...`), not its harness id |
| Can a child read Drive and comment on a PR? | yes, both |

Earlier (2026-11-17): a cloud child cannot message its parent (`05b-orchestra-cloud.md` section 2b).

## 13. The build, from today

1. Remove `project.json` and `config.py`; read protected branches from the forge; the plan carries the rest.
   Done: PR 61 and 62.
2. Plan: repository by URL, scope, locked acceptance tests, plan branch, the ready check. Done: PR 61 (repos, ready
   report) and PR 63 (a card's `acTests`, `orchestra.lock` on `plan/p<n>`, children start from it and cannot change
   them, the check runs them, accept into the plan branch, land ends with one pull request into the base).
3. Drive: `db/` and `tickets/`; the harness writes the ticket CSV. Done: PR 64 (the hook keeps the ids of `db/` and
   `tickets/` from Drive's answers; new ledger copies go to `db/`; `orchestra.tickets` opens one issue per child with a
   hashed machine block and writes the ticket CSV, uploaded by its hash; spawn of a locked plan waits for both).
4. Child: `take` registers the issue and checks the match; its plan is approved by its scope. Done: PR 66 (the
   child's harness reads its issue block and hash from GitHub; the hook checks the downloaded ticket row at Drive's
   answer and keeps only the result; a mismatch pushes question 1 with the reason and stops; commits name #N).
5. CI: `harness ci` with the hard rules; the parent watches the PR (the doorbell). Piece 1 done: PR 67 (the issue
   format `harness-issue/1`; the registration as the first commit of the branch, named by the card plan's approval;
   commits start `#N <name>: `; a child adds files only inside its scope; `cli ci` checks it all from the branch).
   Piece 2 done: PR 68 (`lock` writes the CI workflow on the plan branch, pinned to the harness's main commit, and
   the parent's check refuses a changed one). Next: piece 3 (draft PR and watch), 4 (the doorbell).
6. Orders: signed one-way messages, checked at the notifications door, each unlocking one action.
7. End: every PR merged stops the children; form 2; archive; ledgers to `db/`; join.
8. Docs and the user's specs (13, 05) brought in line.

## 14. Decided by the user (2026-11-18)

- `project.json` is removed fully; each repository sets up its own protection, pipeline and checks.
- A plan names its repository by URL; the repository's CI is the gate.
- The parent writes the acceptance tests before the children start; they are locked.
- Visibility does not matter, as long as the user's account can reach the repository.
- The ticket file is a CSV kept as a file in Drive `tickets/`; ledgers go to `db/`.
- Parent to child: signed one-way orders; child to parent: through git and CI only.
