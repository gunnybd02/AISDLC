---
name: refused
description: A tool call was refused, denied, blocked or asked - what each harness refusal means (plan, shell, git, commit, state, form, stop) and the right next move.
---
# Refused
A refusal names its reason. Do what the reason says; never try another spelling of the same call.

## When to use
- When a hook refuses or asks about a tool call, or an action answers an error.

## Edits and reads
| Finding | Meaning | Move |
|---|---|---|
| `plan.none` | no plan is approved in this session | `guide("work", "skills")`, part 2: present, ask the form |
| `plan.outside` | the plan does not name this file | `add file` or `plan_revise` (`guide("work", "skills")`, part 3) |
| `write.state`, `read.state` | `.claude/state/` is closed to every tool | `run("ledger", "db_query", {"sql": "SELECT ..."})` |
| `agent.rules` | a rule file in `.claude/rules/` | write a skill: `guide("harness-dev", "skills")` |
| `agent.memory` | a memory file | tell the user; notes are not built yet |
| `agent.registry` | the behaviour registry file | the `add test` and `behaviors add` doors |
| `agent.anchor` | `anchor.py`, `.claude/settings.json`, `.mcp.json`, `.claude/entry/boot.py` | the user changes these outside a session |
| `agent.session_start` | a session ran the session start itself | `python3 <core>/anchor.py cli live update` |

## The shell
| Finding | Meaning | Move |
|---|---|---|
| `shell.unexplained` | the harness cannot read the command whole, and the call has no words on it | say in the tool's description what the command does and what it changes (three words at least), run it again |
| `shell.unread` | the same, with words: the user is asked in Claude Code's own prompt | wait for the user |

The reader cannot see whole: an unknown program or script, `$(...)`, backticks, a path from a variable or a
wildcard, inline code that may write. Simple commands with plain paths pass without a question.

## Forms
| Finding | Meaning | Move |
|---|---|---|
| `form.prefilled` | the call carried answers | call AskUserQuestion with the questions alone |
| `form.forged` | a question or label holds `"="` | ask the question exactly as the harness gave it |

## Git and commits
| Finding | Meaning | Move |
|---|---|---|
| `commit.raw` | a commit from the shell | `run("plan", "step_done", {"message"})` |
| `git.add_all`, `git.no_verify`, `git.reset_hard`, `git.force_push`, `git.protected_write`, `push.never_repo`, `push.agent_files`, `git.unread` | a protected branch is touched | `guide("work", "skills")`, part 4: `run("git", "run", ...)` and the user's word |
| `commit.secret` | a secret in an added line | take it out of the file, revoke it, verify again |
| `commit.ai_mark` | an AI co-author, footer, tool name, robot emoji or Mermaid diagram in the message | write the message as the author of the change |
| `commit.banned_word` | a word `project.json` bans | say it another way |
| `commit.agent_files` | agent files in a unit's commit | `add drop-file` |

## Google Drive
`drive.remove`, `drive.move`: a Drive file would be trashed, moved or renamed. The user is asked each time, because
the ledger store on Drive only grows (`guide("store", "skills")`). Uploading and reading are free.

## Orchestra
| Answer | Meaning | Move |
|---|---|---|
| `the delegated plan ... runs in this session`, `GATE: plan ... was not opened` | a plan with children runs; another would orphan them | finish it (children hand back, it closes) or `plan_revise` it |
| `no delegated plan is in force` | spawn needs a plan with children the user approved | present it, ask the form |
| `3 children run already` | the cap | wait until one is accepted or forgotten |
| `has started already`, `one session is one child` | the crew has it | `run("orchestra", "status", {})` |
| `child.no_keyboard`: a step that would ask a person | this session is a child: nobody answers, so it is refused | do not retry it; go on, and name it under notChecked in `handback` |
| `child.ask_user`, `child.merge`, `child.push_other`; `a child session never ...` | this session is a child: nobody answers it, only the orchestrator merges | `run("orchestra", "question", {"question"})`, or name it under notChecked in `handback` |
| `this session is no child` | take, push, question and handback are a child's | a parent uses spawn and started |
| `has not passed a check this round` | accept needs a green check after the last send-back | `run("orchestra", "check", {"name"})` |
| `holds no receipt`, `not handed back since it was sent back`, `tip ... is not its receipt` | the branch does not hold a fresh receipt as its last commit | wait for the child's "handed back", or `reject` it |
| `the user decides now` | 3 send-backs already | ask the user: forget it, or what to do |
| `have not ended` (land) | a child still runs | check and accept it, or forget it |

## The end of a turn
`store.unsaved`: commits, plan events or pushes of this session are in no copy of the store. Export and upload one
(`guide("store", "skills")`); when that cannot be done, say so and the turn ends.

`stop.unverified`: code files of the plan changed since the last green verify. Run
`python3 <core>/anchor.py cli verify` (or `run("verify", "run", {"plan": "<pd-id>"})`) and fix what is red.

## When the harness itself is in the way
- A refusal that looks wrong: tell the user what was refused and why it looks wrong. Do not work around it.
- The guards can be turned off for a while only by the user: `run("maint", "grant", {"minutes": 10, "why": "..."})`
  gives the form question; ask it. `run("maint", "status", {})` says whether they are off.
- A broken harness blocks every call (exit 2): `run("health", "doctor", {})` names each problem.
