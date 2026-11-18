# The map of the brain

The harness is one brain. A session opens it in one folder (the core, `.claude/` with its config and its ledger) and
goes to work from there, on one repository or many. Every session runs under it, on the user's computer or in the
cloud, alone or with others.

This map is the frame for every later plan: each plan says which part it changes. Four parts are general, the same
everywhere; everything else is a plug-in.

**The target** is `system.md` (agreed on 2026-11-18): no `project.json`; a plan names its repository by URL and the
repository's own CI, protection and issues are the authority; children work on issues and are checked by CI and by
the parent's acceptance tests; two forms per piece of work. Where this map and `system.md` differ, `system.md` is
where the plans go.

```text
            THE BRAIN (one core folder, opened by every session, local or cloud)
   ┌──────────────┬──────────────┬──────────────┬──────────────┐
   │   Sessions   │     Plan     │      DB      │  MCP server  │   general: the same everywhere
   └──────────────┴──────────────┴──────────────┴──────────────┘
     plug-ins: blocks (GitHub, GitLab, Jira, Confluence, Drive...), pipelines (the dev harness...), units (repos)
                                   │
                   goes to work in: repo 1 → repo 2 → ... repo N
```

The user's specs (03 tools and blocks, 04 plan lifecycle, 05 orchestra, 12 database) describe the computer version.
The cloud version follows their general parts and leaves the details of each plug-in to its own plan.

## 1. Sessions: who works, alone or together

**In general.** Start, list, message, hand over and close sessions; work side by side on one machine or across
machines; a parent hands parts of a plan to children. A request that only the user may make is refused when the turn
came from another session.

| Done here | Missing | Next |
|---|---|---|
| Orchestra (`docs/05b-orchestra-cloud.md`): a parent plan with children as cloud sessions, each on its own branch and pull request, checked, landed, archived; the child's ledger in the Drive store first | One session layer for the computer and the cloud (list, start, message, hand over, close); orchestra built on it instead of beside it | **The Sessions plan**: one session layer with two hosts; orchestra becomes one user of it |
| A child is bound by its brief and cannot ask the user | Children that can work on the harness itself (today a child is refused any change of `.claude/`) | In the same plan |
| The ledger marks a prompt that is not the user's own words (`docs/12-ledger.md`) | "Only when the user asks" as a general rule for request actions | In the same plan |

## 2. Plan: the one way work is approved and proven

**In general.** A plan is data; the user approves the exact block in a form; only the files of the plan change; a
commit needs a green verify of the exact content; steps; delivery; close.

| Done here | Missing | Next |
|---|---|---|
| The plan desk, tiers, the approval form, the file gate, verify receipts, steps, the close form, settle (`docs/architecture.md`) | A lane per plan: a worktree on the computer, a branch in the cloud | With the Sessions plan, where parallel work needs it |
| The block and its answers as spec 04 says (PR 43, and the fixes of plan "Finish the Plan and DB parts") | Units as first-class: a normal plan works in the folder the server started in; registering a plan's units | A Units plan, after Sessions |
| Behaviours with registered tests; doors to widen a running plan | Delivery followed to its end: the CI of a pushed branch, unmerged commits on the close form | With the GitHub block |

## 3. DB: the brain's memory

**In general.** One ledger records every plan, approval, proof and action, by itself; evidence is hash-chained;
upkeep keeps totals and backups; the model reads it through one read-only query.

| Done here | Missing | Next |
|---|---|---|
| Every call, span, turn, prompt, file write, shell line, skill load and the tokens of each turn are recorded by the harness itself; a schema version with one upgrade door; upkeep; closures; chain check (PR 44, `docs/12-ledger.md`) | One memory across machines: each cloud machine has its own ledger, and the Drive store holds whole copies that are never joined | **In the Sessions plan**: the copies are joined into one ledger by row id |
| The Drive store: a copy at checkpoints, a child's copy before it is archived (`docs/05b-orchestra-cloud.md`) | The transcript archive (raw session content) | Waits for the user's decision: it would go to Drive with every copy |
| | Tools to look back: trace commits to plans, notes, review annotations by plan | A Look-back plan, after Units |

## 4. MCP server: the brain's hands

**In general.** Three tools (`find`, `guide`, `run`); every ability is an action of a block behind `run`; a write is
judged by the rules; consent comes through a form; the surface reloads when its code changes.

| Done here | Missing | Next |
|---|---|---|
| The three tools; 7 blocks with 41 actions (`plan`, `git`, `ledger`, `orchestra`, `maint`, `verify`, `health`); the shell door when the tools do not load; the harness updates itself at session start | A trusted way to plug in other MCP servers (the gateway) | A Plug-ins plan |
| 5 skills (`work`, `harness-dev`, `refused`, `store`, `orchestrate`) | The skills table: work refused until its skills and unit documents are read | With the Units plan |

## 5. Plug-ins

A plug-in is chosen per brain. It never changes how the four parts work; it adds actions, rules or a pipeline.

| Kind | Here | On the computer |
|---|---|---|
| Blocks | GitHub (pull requests through `gh api`), Google Drive (the ledger store) | GitLab, Jira and Confluence (`twg`), docs, context, host, overlay, servers |
| Pipelines | `base`, the floor every session runs (`assemble/pipelines/base.json`) | A pipeline per unit; the dev-harness pipeline |
| Units | Declared in `project.json` (`repo`, `path`, `verify`, `base`); used by orchestra children | Every unit with its own documents and skills |

A plug-in plan adds its block, its rules and its tests, and names in this map which part it serves.

## 6. The order of the next plans

1. **Sessions**: one session layer for the computer and the cloud; orchestra on top of it as `system.md` describes
   (issues, the ticket CSV, CI as the gate and the doorbell, signed orders, two forms); children that can work on the
   harness itself; Drive `db/` copies joined into one memory.
2. **Repositories by URL** (was "Units"): `project.json` removed; the plan names its repository; the ready check;
   protected branches read from the forge; the skills table.
3. **Look-back**: trace, notes, reviews, cost by plan.
4. **Plug-ins**: the gateway for other MCP servers, then each block the user names.

Each is one total plan, approved in one form, built step by step through the harness.
