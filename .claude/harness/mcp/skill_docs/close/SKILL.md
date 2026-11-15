---
name: close
description: Close the session's plan with plan_close and its form (delivered, abandoned, keep open), and settle old open plans with plans_settle.
---
# Close
A plan ends by what the ledger proves, and by the user's answer.

## When to use
- When the work of a plan is done or given up, and when old plans are still open.

## Steps
1. A plan in the home closes itself as delivered after its last `step_done`: nothing more to do.
2. Any other plan: `run("plan", "plan_close", {"summary": "<what was done>"})`. The harness builds the account from
   the ledger (commits, files against the plan, verify, skipped steps) and answers with the close form.
3. Ask the form with AskUserQuestion exactly as given. Only the user's answer closes the plan:
   "Đã giao" (delivered), "Bỏ plan" (abandoned), "Giữ mở" (it stays open).
4. Tell the user in one or two lines what was delivered and what was not.

## Old plans
- `run("ledger", "plans_settle", {})` lists the open plans and what proves their end.
- `run("ledger", "plans_settle", {"write": true})` ends the proven ones.
- `run("ledger", "plans_settle", {"drop": ["<pd-id>"]})` ends unproven plans of sessions that no longer run: the
  answer is a form; ask it, and after the user's "Cho phép" call it again with the same plans.

## Notes
- `run("plan", "plan_status", {})` says where the session's plan stands before closing.
- A plan is delivered only when its commit holds the plan's files as the green verify saw them.
