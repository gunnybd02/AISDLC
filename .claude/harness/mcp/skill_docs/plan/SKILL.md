---
name: plan
description: Write a plan, present it with plan_present, ask the user's approval form, revise or drop it - before any edit.
---
# Plan
A plan is data the user approves in a form. After the approval only the plan's files may change.

## When to use
- Before the first edit of a piece of work, and when the work needs a file the plan does not name.

## Steps
1. Stand in the repository the work is in: the plan's root is the folder the call is made from, and every path of
   the plan is relative to it (no `..`, nothing in `.git`).
2. Pick the tier.
   - Light (a small change): `title`, `what`, `files`, and `tests` when there are any.
   - Full (anything with steps): add `steps`, and then `services`, `checks`, `assumptions`, `notDoing`, `risks`,
     `overview` and `code` are needed too.
3. `run("plan", "plan_present", {"plan": {...}})`. Problems come back as a list: fix all of them, present again.
4. The answer ends with the form call. Write one line (the title and the revision), then call AskUserQuestion with
   exactly that question, header and options. Nothing after it, and never fill in the answer.
5. "Duyệt" opens the plan: go to `guide("step", "skills")`. "Sửa plan": take the user's words,
   `run("plan", "plan_revise", {"plan": "<pd-id>", "changes": {...}})` with only the items that change, ask the new form.

## A light plan
```json
{"title": "Fix the date parser", "what": ["A date without a year reads as this year"],
 "files": ["src/dates.py"], "tests": ["tests/test_dates.py"]}
```

## A full plan
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
- Points (`what`, `checks`...): at most 10, each at most 200 characters. `overview`: all four keys, at most 5 each.
- A behaviour id looks like `a.b-c`; one in a step becomes `s<n>.<id>`. Each needs `what`, `how`, `why`.
- `services`: `agent-code` (the work is in this root) or the declared units.

## Reading a plan
- `run("plan", "plan_show", {})`: the plan as the user reads it, with its form call.
- `run("plan", "plan_status", {})`: revision, state, feedback not answered, the session's ticket.
- `run("plan", "plan_drop", {})`: stop a plan that still waits for approval.

## Notes
- A new plan approved while another is open closes the old one as superseded: to change work in hand, revise.
- One more file in an approved plan, with no new approval: the `add file` door in `guide("step", "skills")`.
