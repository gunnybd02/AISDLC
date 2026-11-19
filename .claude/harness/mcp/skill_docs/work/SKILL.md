---
name: work
description: Start here in every session - the whole workflow under the harness in one file, gather context, write and present a plan, the approval form, build each step, tests, verify, step_done, commit, push, merge request, close the plan.
---
# Work
Read this first in every session. The harness judges each tool call; work passes only through an approved plan. This
is the whole way, from the request to the closed plan.

## The tools
| Tool | Use |
|---|---|
| `find(query, mode?)` | the skills and tool blocks that fit some words |
| `guide(name, mode)` | read a skill (`mode: "skills"`) or the actions of a block (`mode: "mcp"`) |
| `run(block, action, args)` | run one action |

With the MCP server they are `mcp__harness__find`, `mcp__harness__guide`, `mcp__harness__run`. Without it, the same
from the shell (`<core>` is the path the session-start message names):
```
python3 <core>/anchor.py cli tool find <words>
python3 <core>/anchor.py cli tool guide <name> --mode skills
python3 <core>/anchor.py cli tool run <block> <action> '<args as JSON>'
```

## Always
- No edit before the user's "Approve" in the form. A typed "ok" approves nothing.
- Only the user answers a form: call AskUserQuestion with the questions alone, exactly as the harness gave them.
- Never `git commit` in the shell: `step_done` commits.
- Never open `.claude/state/`: read the ledger with `run("ledger", "db_query", {"sql": "SELECT ..."})`.
  The harness records every call, shell line, file write, skill load and the tokens of each turn by itself;
  you record nothing. `run("ledger", "chain_check")` says whether the evidence is whole.
- Say in a shell call's description, in plain words, what the command does and what it changes.
- A call was refused: read the reason, then `guide("refused", "skills")`. Never look for a way around a gate.
- The work is on the harness itself: `guide("harness-dev", "skills")`.

## 1. Gather context
Reading needs no plan. Read the code the request touches, its tests, and how the repository runs them (its CI, its
README). Ask the user what is unclear. Go on when you can name every file to change and the test of each behaviour.

## 2. Plan
1. Stand in the repository the work is in: the plan's root is the folder the call is made from, and every path of
   the plan is relative to it (no `..`, nothing in `.git`).
2. Pick the tier. Light, for a small change: `title`, `what`, `files`, and `tests` when there are any.
   ```json
   {"title": "Fix the date parser", "what": ["A date without a year reads as this year"],
    "repos": {"shop": {"url": "https://github.com/acme/shop", "base": "main", "verify": ["npm", "test"]}},
    "files": ["src/dates.py"], "tests": ["tests/test_dates.py"]}
   ```
   `repos` names the repository the plan works in, by URL, with its test command (`verify`, a list of words;
   `{python}` is this Python), its base, and optionally `path` (a folder) and `pipeline`. Form 1 shows it. The plan's
   folder must be a clone of one of its repos; that repo's `verify` is what verify runs. A plan with tests needs one;
   a plan with no tests (docs) needs none. `limits` may lower the orchestra limits, `banned` adds words commit text
   never holds.
   Full, for anything with steps: `steps`, and then `overview`, `code`, `services`, `checks`, `assumptions`,
   `notDoing` and `risks` are needed too.
   ```json
   {"title": "Add the export door",
    "overview": {"problem": ["..."], "need": ["..."], "how": ["..."], "accept": ["..."]},
    "services": ["agent-code"], "what": ["..."], "checks": ["..."], "assumptions": ["..."],
    "notDoing": ["..."], "risks": ["..."],
    "code": [{"file": "src/export.py", "code": "def export(rows): ...", "reason": "the one new function"}],
    "steps": [{"commit": "Add export", "points": ["write export()"], "files": ["src/export.py"],
               "tests": ["tests/test_export.py"],
               "behaviors": [{"id": "export.csv", "what": "rows become CSV lines", "how": "unit test",
                              "why": "the user reads them in a sheet", "test": "tests/test_export.py"}]}]}
   ```
   - `title`: one line, 3 to 80 characters, two words at least, no double quote.
   - Points (`what`, `checks`...): at most 10, each at most 200 characters. `overview`: all four keys, 5 points each
     at most.
   - A behaviour id looks like `a.b-c`; one in a step becomes `s<n>.<id>`. Each needs `what`, `how`, `why`.
   - `services`: `agent-code` (the work is in this root) or the declared units.
3. `run("plan", "plan_present", {"plan": {...}})`. Problems come back as a list: fix all of them, present again.
4. The answer ends with the form call. Write one line (the title and the revision), then call AskUserQuestion with
   exactly that question, header and options. Nothing after it.
5. "Approve" opens the plan. "Change plan": take the user's words,
   `run("plan", "plan_revise", {"plan": "<pd-id>", "changes": {...}})` with only the items that change, ask the new form.

`run("plan", "plan_show", {})` shows the plan as the user reads it; `run("plan", "plan_status", {})` its state;
`run("plan", "plan_drop", {})` stops one that still waits. A new plan approved while another is open closes the old
one as superseded: to change work in hand, revise.

**Parts for child sessions**: the whole procedure is the skill `orchestrate` (`guide("orchestrate", "skills")`). In
short (`docs/05b-orchestra-cloud.md`): a full plan with `children`, each card
`{name, unit, goal, ac, read?, change, tests?, acTests?, actions?}`; each AC names a visible case; a unit is `home`
or a repo the plan names in `repos` (any repository, or a folder of a shared one). One "Approve" approves them all;
then write the acceptance tests (`acTests`) and `run("orchestra", "lock", {})` pushes them on the plan branch
`plan/p<plan>`; per child, `run("orchestra", "spawn", {"name"})` gives the brief and the `create_session` call, and
`run("orchestra", "started", {"name", "sid"})` records it (3 run at most; `run("orchestra", "status", {})`). While it
runs no other plan opens in the session; revise it instead. When a child says "handed back":
`run("orchestra", "check", {"name"})` (its receipt, the locked tests unchanged and run here), then `accept` (one pull
request into the plan branch) or `reject` with why (3 rounds). A question: `answer`. Both push a note and give the
signed order (fix or answer) for the child's running session: send it with `send_message` as given. When every child
has ended: `run("orchestra", "land", {})` merges the pull requests into the plan branch; a conflict stops it with the
two ways on (resolve it on the child's branch, or reject); green gives each child a signed stop order, opens one pull
request of the plan branch into the base, and asks form 2 (merge it, delete the branches, archive the child sessions).
On the user's Allow merge it with the merge tool, land again: it deletes the branches, gives the archive calls, closes.

**A child session** (its first prompt is a brief: `You are child session ...`): nobody is at its keyboard.
`run("orchestra", "take", {})` first. When the brief names an issue and a ticket file, take registers you before any
work: it gives two Drive calls (find the ticket file, download it once); the harness checks the file and the issue
against the brief and keeps no copy; run take again. Registered, the harness commits the registration commit
(`.harness/register/<name>.json`) as the first commit of your branch, made from the plan branch, and pushes it; your
card plan opens on it (the locked acceptance tests: make them pass, never change them; the doors refuse them, and any
file outside your card's change and tests). Every commit names #N by itself: it starts `#N <name>: `. On the forge,
`harness ci` checks the same rules again from your branch alone (`python3 <core>/anchor.py cli ci --base <plan branch>
--head <your branch>`). "Registration failed": the reason is pushed on your branch for the orchestrator; stop at once.
Then the loop of part 3, and
`run("orchestra", "push", {})` after every step. A question: `run("orchestra", "question", {"question"})`. Last:
`run("orchestra", "handback", {"changed", "checked", "notChecked", "risks", "testsChanged"})`. Both are pushed, and
the harness posts each as a comment on your draft pull request: that is how your words reach the orchestrator, whom
the CI result of your push wakes. Never `send_message` (auto mode refuses it), then stop: you wait, and the harness
lets you change nothing until a signed order of the orchestrator arrives in your notifications (ReadNotifications).
A valid fix or answer opens one more round; stop: export and upload your ledger, then end. An order that does not
check out is ignored. Never AskUserQuestion, a plan of its own, a merge or a close.

## 3. Build each step
1. Edit only the files the plan names; any other file is refused.
2. Write the step's tests: each behaviour of the step needs its test file to exist.
3. Verify: `run("verify", "run", {"plan": "<pd-id>"})`, or `python3 <core>/anchor.py cli verify` (another command:
   add `-- <command>`; a longer run: `--timeout <seconds>`). It runs the tests in the plan's root and keeps a receipt
   of each file as the tests saw it.
   Run tests only this way, never `python3 -m unittest` or `npm test` by hand: the harness cannot read those, and
   outside auto mode each one asks the user.
4. Red: fix and verify again. A file changed after a green verify needs a new verify.
5. Green: `run("plan", "step_done", {"message": "<the commit message>"})`. The harness checks what the step owes and
   commits its changed files; the next step opens. Write the message as the author of the change: no AI co-author,
   footer or tool name, no robot emoji.
6. A step that will not be done: `run("plan", "step_skip", {"why": "<one line>"})`, with changed plan files put back.
7. When an answer ends with a `Store:` line, or the end of a turn is held for the store (`store.unsaved`), the
   ledger's copy is due: `guide("store", "skills")`.

| `step_done` refuses | Move |
|---|---|
| `step-nothing-to-commit`: no plan file changed | do the work, or `step_skip` |
| `step-other-files`: a changed file belongs to another step | commit it in its own step |
| `step-owed`: a behaviour without its test, or no green verify of the current files | write the test, verify again |
| `step-protected-branch`: the branch is protected | work on a branch of the plan |
| a commit guard: a secret, an AI mark, a banned word, agent files | `guide("refused", "skills")` |

One more file or test with no new approval, from the shell:
```
python3 <core>/anchor.py cli add file <path> --behavior <id> --why "<why>"
python3 <core>/anchor.py cli add test <test file> --behavior <id> --what "<what it proves>"
python3 <core>/anchor.py cli add drop-file <path> --why "<why>"
python3 <core>/anchor.py cli behaviors add <id> --what "..." --how "..." --why "..." --test <file>
python3 <core>/anchor.py cli behaviors list
```
A wider change (a new step, another unit) is `plan_revise` and a new form. The turn does not end while a code file of
the plan changed since the last green verify.

Shell commands: write them plain (one command, plain paths), and edit files with the Edit and Write tools. A command
the harness cannot read whole (a script, a loop, `$VAR` paths, `git checkout <branch>`) asks the user, except in
auto mode: there it runs, and the harness compares the repositories before and after. A file it changed outside the
plan is named right after (`plan.outside_after`) and holds the turn (`stop.outside`) until it is undone or added.

## 4. Ship
- Commit named files outside a step: `run("git", "commit", {"files": ["a.py"], "message": "..."})`. Paths from the
  plan's root, never `.` or a folder; the next `step_done` adopts the commit.
- Push: `run("git", "push", {})` pushes the plan's branch to origin, after the last step, from a unit's repository,
  on a branch that is not protected. The repository that holds the harness never pushes this way.
- Merge request: push first, then `run("git", "mr_open", {"title": "...", "description": "...", "target": "main"})`.
  The answer is a form with the full text; ask it exactly as given, and after the user's "Allow" call `mr_open`
  again with exactly the same text. No AI mark and no banned word in it. It goes through GitLab REST.

Git is free except where a protected branch is touched (`main`, `master`, the branches the repository protects on
GitHub, and the base of the plan in force). There
these ask the user first: `git add -A`/`.`, `--no-verify`, `reset --hard`, a force push, any write on the branch, a
push from the harness's repository, agent files (`.claude/`, `CLAUDE.md`, `.mcp.json`, `AGENTS.md`) staged or
pushed, git with `-c`/`--git-dir`/`--work-tree`. To run one:
`run("git", "run", {"repo": "<folder>", "args": ["push", "origin", "work"]})` (`args` are the words after `git`). Asked:
the answer is a form question; ask it exactly as given, then run exactly the same command again. Prefer a branch of
the plan and a merge request.

## 5. Close
1. A plan in the harness's own repository closes itself as delivered after its last `step_done`.
2. Any other plan: `run("plan", "plan_close", {"summary": "<what was done>"})`. The harness builds the account from
   the ledger and answers with the close form. Ask it exactly as given; only the user's answer closes the plan:
   "Delivered", "Drop plan" (abandoned), "Keep open" (it stays open).
3. Tell the user in one or two lines what was delivered and what was not.
4. Old plans still open: `run("ledger", "plans_settle", {})` lists them and what proves their end; with
   `{"write": true}` it ends the proven ones; `{"drop": ["<pd-id>"]}` ends unproven plans of sessions that no longer
   run, after the user's "Allow" in the form it gives.
