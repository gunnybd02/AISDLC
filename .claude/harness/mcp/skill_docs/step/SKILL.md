---
name: step
description: Build one step of an approved plan - edit only plan files, write the tests, run verify, end with step_done, skip a step, add a file or a test.
---
# Step
After "Duyệt" the plan is in force. Work one step at a time; the harness commits each step itself.

## When to use
- From the approval of a plan until its last step is done.

## Steps
1. Edit only the files the plan names. Any other file is refused (`plan.outside`).
2. Write the step's tests: each behaviour of the step needs its test file to exist.
3. Verify: `run("verify", "run", {"plan": "<pd-id>"})`, or from the shell
   `python3 <core>/anchor.py cli verify` (another command: add `-- <command>`; a longer run: `--timeout <seconds>`).
   It runs the test command in the plan's root and keeps a receipt of each file as the tests saw it.
4. Red: fix and verify again. A file changed after a green verify needs a new verify.
5. Green: `run("plan", "step_done", {"message": "<the commit message>"})`. The harness checks what the step owes and
   commits its changed files. The next step opens; after the last one the plan is in deliver.
6. A step that will not be done: `run("plan", "step_skip", {"why": "<one line>"})`. Put changed plan files back first.

## What step_done refuses
| Code | Meaning | Move |
|---|---|---|
| `step-no-message` | no message | give one |
| `step-nothing-to-commit` | no plan file changed | do the work, or `step_skip` |
| `step-other-files` | a changed file belongs to another step | commit it in its own step |
| `step-owed` | a behaviour without its test, or no green verify of the current files | write the test, verify again |
| `step-protected-branch` | the branch is protected | work on a branch of the plan |
| a commit guard | a secret, an AI mark or a banned word in the message, agent files | see `guide("refused", "skills")` |

## Widening the plan without a new approval
From the shell, for the session's plan:
```
python3 <core>/anchor.py cli add file <path> --behavior <id> --why "<why>"
python3 <core>/anchor.py cli add test <test file> --behavior <id> --what "<what it proves>"
python3 <core>/anchor.py cli add drop-file <path> --why "<why>"
python3 <core>/anchor.py cli add retire-test <test file> --why "<why>"
python3 <core>/anchor.py cli behaviors add <id> --what "..." --how "..." --why "..." --test <file>
python3 <core>/anchor.py cli behaviors list
python3 <core>/anchor.py cli behaviors check
```
A wider change (a new step, another unit) is `plan_revise` and a new form: `guide("plan", "skills")`.

## Notes
- The message is written as the author of the change: no AI co-author, footer or tool name, no robot emoji.
- The turn does not end while a code file of the plan changed since the last green verify: verify first.
- A write to a plan file after the last step sends the plan back to execute; the next `step_done` is a fix.
