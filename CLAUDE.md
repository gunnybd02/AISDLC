# AISDLC harness

This repository is the harness: the brain every session opens. You work **through** it, never around it. It
plans, guards, proves and remembers, so the user can trust what was done.

## How to use the harness

- **Three tools.**
  - `find`: what exists.
  - `guide`: how a block or skill works.
  - `run`: do one action.
  - When unsure, `find`, then `guide`, then `run`.
- **One way to change anything.** Plan, the user approves, build step by step, prove, ship.
  - `plan_present` shows the plan. The user answers the form it prints.
  - Each step ends green: verify, then `step_done`.
  - Shipping is a pull request, merged after the user allows it.
- **The ledger remembers.** Every call, plan and decision is recorded by the harness itself. Ask it
  (`run('ledger', 'db_query', ...)`) instead of guessing.
- **A refusal is guidance.** When the harness refuses or asks, read why. It names the next step. Follow it, or fix
  the plan. Never work around it.
- **The doctor keeps it whole.** `python3 anchor.py doctor` and the suite stay green.

## Mindset

- **The user decides; you propose.** Only the user's "Approve" in the form approves. A chat word approves nothing,
  and you never answer a form yourself.
- **Understand before you build.** Read what exists, find the owner of a concept, and change it there. Prefer one
  owner over a copy.
- **Design before a big change.** Explain it simply, agree on it, then plan.
- **Prove, don't claim.** A thing is done when a test or a real run shows it. Say plainly what was not checked.
- **Small and honest steps.** One concern per step, each green. Report mistakes as soon as you see them.
- **Simple words.** Short English, the result first, tables when they help.

## Where to look

- `.claude/docs/map.md`: the four parts (Sessions, Plan, DB, MCP server) and what comes next.
- `.claude/docs/handover.md`: what was built, PR by PR.
- `.claude/docs/13-cloud-foundation.md`: the structure rules and how they are kept.
- The user's specs (03, 04, 05, 12, 13) are the source of truth.
