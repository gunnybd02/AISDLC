# Testing the harness in a real Claude Code session

The unit tests drive each piece; this is how the whole harness runs inside a live session, as it was checked on
2026-11-14 (a headless `claude -p` session on Linux).

## Wire it into a project

The project is a git repository with this `.claude/` folder in it (the home). Add `.claude/project.json`:

```json
{"name": "live", "verify": ["{python}", "-m", "unittest", "discover", "-s", "."]}
```

`.claude/settings.json` sends every hook event to the harness:

```json
{"hooks": {
  "PreToolUse":       [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/entry/boot.py\" hook"}]}],
  "PostToolUse":      [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/entry/boot.py\" hook"}]}],
  "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/entry/boot.py\" hook"}]}],
  "Stop":             [{"hooks": [{"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/entry/boot.py\" hook"}]}]}}
```

`.mcp.json` in the project root gives the model the harness's MCP server (on Windows: `python` and a Windows path):

```json
{"mcpServers": {"harness": {"type": "stdio", "command": "python3", "args": [".claude/entry/boot.py", "mcp_server"]}}}
```

Then publish the code once (the user answers the form it gives): `python3 -m entry.cli live publish` from
`.claude/`. Until a release is published, boot runs the work tree.

## Run it

Interactive: start `claude` in the project and ask for a change. Headless, for a scripted check (normal permission
mode; pre-allow only the tools of the test, the hooks stay the gate):

```bash
claude -p "Create hello.py that prints hello" --output-format stream-json --verbose --max-turns 12 --mcp-config .mcp.json --allowedTools "Write,Edit,Read,Bash,AskUserQuestion,mcp__harness__find,mcp__harness__guide,mcp__harness__run"
```

A headless session cannot answer a form: the user's click on "Duyệt" is the hook event a form answer gives
(PostToolUse of AskUserQuestion with `tool_response.answers`), sent to `entry/hook.py` with the session's id.

## What the live run showed

| Step | The harness answered |
|---|---|
| Write before any plan | refused: no plan approved |
| `plan_present` with a sentence as a test | refused by the desk; a light plan was then kept (root: the project) |
| The form answered "Duyệt" | ticket opened in execute |
| Write `hello.py`, `verify.run` | allowed; verify passed |
| `step_done` with an AI co-author line | refused by the commit guard; the model wrote the message again |
| `step_done` | committed; the plan delivered, its ticket closed |
| `cat .claude/state/harness.db`, `git commit` in the shell | refused, each naming its door |

Three bugs it found, fixed with a test each: the harness's own CLI (`python3 -m entry.cli verify`) was asked of the
user as an unknown program; `plan_status` counted the approval word as unanswered feedback; the refusal of a shell
`git commit` still named the old `steps` block.

A second live run (boot wiring): the MCP server and the hooks ran through `entry/boot.py`; writing a new action file
was refused (no plan), editing `entry/boot.py` was refused as an anchor, and the server's actions did not change.

## Every session of a machine: install

`python3 .claude/entry/install.py` (from a clone of this repository) installs the harness for every Claude Code
session of the user: its hooks merged into `~/.claude/settings.json` (the user's own hooks stay) and its MCP server
at user scope (`claude mcp add-json --scope user`, else `~/.claude.json`). The clone is the harness's home (ledger,
config, releases); the repositories a session works on are its plan roots. It is safe to run again;
`--uninstall` takes out only what it put in.

A cloud environment gets the latest harness in every new session with a setup script, run before Claude starts:

```bash
git clone -q --depth 1 https://github.com/gunnybd02/AISDLC "$HOME/.harness" && python3 "$HOME/.harness/.claude/entry/install.py"
```

Checked: a fresh home, the clone, install, then a session in an unrelated repository: the `harness` MCP server
connected and the first write was refused (no plan).

In a cloud session Claude Code can be started before the setup script runs: the hooks are read when they fire, so they
govern it, but the MCP server is loaded only at start, so the session has no `mcp__harness__` tools. The same tools
are a shell command away (the same server, actions and judge; the hook links the session that runs it):

```bash
python3 ~/.harness/.claude/entry/boot.py cli tool guide plan
python3 ~/.harness/.claude/entry/boot.py cli tool run plan plan_present '{"plan": {"title": "...", "files": ["a.py"]}}'
python3 ~/.harness/.claude/entry/boot.py cli tool find verify tests
```

A refusal that names `run(...)` says so, with the home's own path.
