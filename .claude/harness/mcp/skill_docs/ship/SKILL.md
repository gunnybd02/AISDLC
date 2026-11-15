---
name: ship
description: Ship a change - commit named files, push the plan's branch, open a merge request, run git on a protected branch with the user's word.
---
# Ship
Commits, pushes and merge requests go through the harness, so each one is judged and kept in the ledger.

## When to use
- To commit outside `step_done`, to push, to open a merge request, or when a git command was asked or refused.

## Commit
- The usual way is `run("plan", "step_done", {"message"})`: see `guide("step", "skills")`.
- Named files only: `run("git", "commit", {"files": ["a.py"], "message": "..."})`. Files are paths from the plan's
  root, never `.` or a folder. The step does not move; the next `step_done` adopts the commit.
- `git commit` in the shell is always refused (`commit.raw`), and so is any line that may commit another way.

## Push
- `run("git", "push", {})` pushes the branch of the session's plan to origin. It works in deliver (after the last
  step), from a unit's repository, on a branch that is not protected.
- The home (the repository that holds the harness) never pushes this way: `git-home-never-pushes`.

## Merge request
1. Push first.
2. `run("git", "mr_open", {"title": "...", "description": "...", "target": "main"})`.
3. The answer is a form with the full text: ask it with AskUserQuestion exactly as given.
4. After the user's "Cho phép", call `mr_open` again with exactly the same text: it opens the merge request.
The text holds no AI mark and no banned word. It goes through GitLab REST.

## Git on a protected branch
Protected branches are `main` and `master`, or `protected` in `project.json`. Elsewhere git is free. Where a protected
branch is touched, these ask the user first:

| Rule | Asked |
|---|---|
| P1 | `git add -A`, `--all`, `.`: stage files by name |
| P2 | `--no-verify`, `commit -n` |
| P3 | `git reset --hard`: use `git stash` or `git restore <file>` |
| P4 | a force push (`--force`, `-f`, `--force-with-lease`, `--mirror`, `+refspec`) |
| P5 | any write on the protected branch |
| P6 | a push from the home |
| P7 | agent files (`.claude/`, `CLAUDE.md`, `.mcp.json`, `AGENTS.md`) staged or pushed |
| P8 | git with `-c`, `--git-dir`, `--work-tree` |

To run one of them:
1. `run("git", "run", {"repo": "<folder>", "args": ["push", "origin", "work"]})`: `args` are the words after `git`.
2. Nothing to ask: it runs. Asked: the answer is a form question; ask it with AskUserQuestion exactly as given.
3. After the user's word, run exactly the same command again: the word is used once.

## Notes
- Prefer a branch of the plan and a merge request over a write on a protected branch.
- Every run of the git block, every push and merge request is kept in the ledger.
