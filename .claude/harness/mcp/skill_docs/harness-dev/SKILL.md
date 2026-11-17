---
name: harness-dev
description: Develop the harness itself, one workflow in one file - gather context with the folder map, plan, add a rule, detector, action or skill, tests and doctor, commit, pull request, merge, publish a release, update sessions, the install.
---
# Harness dev
The whole way of a change to the harness, from reading to the release. It follows `guide("work", "skills")`; this
file adds what is special about the harness. Python 3.13, standard library only, every `.py` file ASCII.

## 1. Gather context
```
anchor.py           the one file Claude Code runs; never written in a session
.mcp.json           the MCP server of this repository (calls the anchor)
.claude/
  settings.json     the hooks of this repository (call the anchor)
  project.json      the user's values: name, verify, protected, banned, ledger
  harness/
    entry/          the doors: hook, mcp_server, cli, doctor, install, session_start
    hooks/          hook JSON in and out, the answers of a form; decides nothing
    gear/           translate/ -> detect/ -> decide/arbiter.py, rule rows in rules/*.json
    mcp/            server/, tools/ (find, guide, run), actions/, skills/ (code), skill_docs/ (texts)
    assemble/       engine/ (connects the blocks) and pipelines/ (which gears run)
    utils/          shared code with no policy: contracts, ledger/, plan/, shell/, git/, gateway/, maint/
    nets/           the rules of the tree, run by the doctor
    tests/          tests/<block>/test_<module>.py, plus nets/ and e2e/
  docs/             architecture.md, handover.md, the specs; not part of a release
  state/            the ledger and the releases; closed to every tool
```
The run of a call: Claude Code -> `anchor.py hook` -> `entry/hook.py` -> `assemble/engine/build.py` -> `hooks/io.py`
(JSON to an event) -> translators (facts) -> detectors (findings) -> `gear/decide/arbiter.py` (the verdict, from the
rule rows) -> the answer. A broken harness exits 2, which blocks the call.

Read `.claude/docs/architecture.md` for the part to change, and `.claude/docs/handover.md` for the open gaps.
`run("health", "items", {})` lists what each block declares.

## 2. Plan
As in the `work` skill: present, ask the form, wait for "Approve". Work on a branch, never on `main`. Name the test
file of each change in the plan. `anchor.py`, `.claude/settings.json` and `.mcp.json` are never written in a
session: a change there is the user's.

## 3. Build
Write the test first: `harness/tests/<block>/test_<module>.py`, named after the module it tests.

Every function says what it takes and gives (the `hints` net): a type hint on each parameter and return, and a
docstring with a first line, `Args:`, `Returns:` and `Raises:`. Name the data with `utils/shapes.py` (`ApprovedPlan`,
`Ticket`, `Receipt`, `PlanStore`...); a dict that recurs gets a new name there. Start each module with
`from __future__ import annotations`.

**A rule** (the harness refuses, asks about or sees a kind of tool call)
1. The fact, when no translator gives it yet: a class on `Translator` (`utils/contracts.py`) in
   `gear/translate/`. `translate(event)` returns a dict of facts. Each fact has one giver.
2. The finding: a class on `Detector` in `gear/detect/`. It reports, it never names a verdict.
   ```python
   class NoTabs(Detector):
       def detect(self, event, facts):
           return [Finding("style.tab", facts["path"])] if facts.get("has_tab") else []
   ```
3. One line in `gear/__init__.py`:
   `{"kind": "detector", "name": "no_tabs", "ref": "harness.gear.detect.style:NoTabs"}`, and its name in
   `assemble/pipelines/base.json`.
4. The row in `gear/rules/` (`place.json`: edits, reads, the shell; `git.json`: git and commits):
   ```json
   {"finding": "style.tab", "verdict": "refuse", "why": "<what to do instead, for the model>",
    "test": "harness/tests/gear/test_style.py#test_a_tab_is_refused"}
   ```
   The verdict is `allow`, `ask` or `refuse`; the strongest wins. A row whose test does not exist does not load; a
   finding with no row asks the user. Add the finding to the `refused` skill.

**An action** (a thing the model runs with `run`)
1. A class in a file of `mcp/actions/`, listed in that file's one literal `ACTIONS`:
   ```python
   ACTIONS = [("notes.list", "List")]

   class List(McpAction):
       block, name, effect = "notes", "list", READ
       summary = "The notes of the session, newest first"
       args_schema = {"type": "object", "properties": {"limit": {"type": "integer"}}, "required": []}
       needs = ("ledger",)

       def run(self, ctx, args):
           return "..."
   ```
   `needs` names ports of `ACTION_PORTS` (`assemble/engine/ports.py`); `run` returns text; `ActionError` says no.
2. A `write` action needs its row in `gear/rules/actions.json` (`"finding": "action.<block>.<name>"`, verdict
   `allow`), or it never runs. A `read` action is never judged.
3. Pin it in `PINNED` of `harness/tests/mcp/test_action_registry.py`. Logic of more than a few lines goes to `utils/`.

**A skill** (a text for the model)
1. `.claude/harness/mcp/skill_docs/<name>/SKILL.md`, starting with a frontmatter of `name` (the folder's) and
   `description` (one line, in the words someone would search with: `find` ranks by them).
2. One kind of work per file, whole, top to bottom; 300 lines at most. Write calls as the model makes them; the
   doctor refuses a skill that names an action, a block or a skill that is not there.

**Other**: a shell door for the user is in `assemble/engine/cli_wire.py` and its `cli_*.py` files; code two blocks
share goes to `utils/`, with no policy in it.

## 4. Check
From `.claude/`: `python3 -m unittest discover -s . -t .` passes and `python3 harness/entry/doctor.py` says
`0 errors`. The doctor runs the nets:

| Net | Rule |
|---|---|
| `layout` | a file is only where `harness/nets/layout.json` allows |
| `imports` | `hooks`, `gear`, `mcp` import only themselves and `utils`; `utils` imports no block; `assemble` connects; `entry` imports only `assemble`, inside `main()` |
| `size` | a `.py` file has at most 400 lines, a `.md` file at most 300 |
| `verdict` | the verdict words appear only in `gear/decide/arbiter.py` and `utils/contracts.py` |
| `config` | `project.json` is named only in `assemble/engine/config.py` |
| `bridges`, `entry` | no file only passes names on; an entry script imports only the standard library at load time |
| `hints` | every parameter and return has a type hint; every function and method a docstring |

## 5. Pull request
1. Commit each step with `step_done` (the `work` skill).
2. Push the branch: `git push -u origin <branch>`. Git is free off a protected branch.
3. Open the pull request on the host (GitHub: the `gh` tool or the web; GitLab: `mr_open`): what changed, the
   tests, what was not tested.
4. The user merges it, or says so in a form and you merge. Never push to `main`, never force push.

## 6. Release
A session never runs the files it edits. It runs a release: a copy of `harness/` under `state/live/<sha>/`.
- A new session takes the newest main at its start, when the doctor is clean.
- A running session: `python3 <core>/anchor.py cli live update` brings merged main and puts it in force when its doctor
  is clean, with no form (the merge was the user's word). No restart.
- The work tree's own code before a merge (a PC): `python3 <core>/anchor.py cli live publish`, the same form.
- `python3 <core>/anchor.py cli live status` says which release is in force.

| Changed | Runs after |
|---|---|
| gear, hooks, rules, skills, actions | the next call once the release is in force |
| `anchor.py`, `.claude/settings.json`, `.mcp.json` | a new session |
| the install | `python3 <core>/.claude/harness/entry/install.py` again |

The install: on a PC, Claude Code is started in the core repository and its own wiring switches the harness on. For
every session of a machine (the cloud), `install.py` writes the hooks into the user's settings, registers the MCP
server and allows the harness's own CLI (`--uninstall` takes it out). One core: an installed harness wins over a
repository's own copy; never two.
