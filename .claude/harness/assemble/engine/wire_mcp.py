"""The MCP door harness/entry/mcp_server.py calls: run_mcp serves find, guide and run, over the action table. The actions are
the classes of the ACTIONS literals of mcp/actions/*.py; the ports are SERVER_PORTS (engine/ports.py), built here, and
run hands each action only those it names in needs. The judge port is the hook's own runner: a write action is judged
by the same rules as a tool call."""
from __future__ import annotations

import shlex
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Optional, Protocol, TextIO

from harness.assemble.engine.build import CLAUDE_DIR, build_runner, code_of, items_of, skill_docs
from harness.assemble.engine.checks import doctor, report
from harness.assemble.engine.config import Config
from harness.assemble.engine.loader import Item, Loader
from harness.assemble.engine.ports import SERVER_PORTS, LedgerPort
from harness.utils.contracts import Event
from harness.utils.git import github
from harness.utils.ledger import store

SERVER = ("harness", "0.1")


class McpServer(Protocol):
    """The MCP server build_server gives (mcp/server/stdio.py StdioServer, loaded by name: assemble names it without
    importing mcp): its tools by name, and how it serves lines."""
    tools: dict[str, Any]

    def serve(self, instream: Iterable[str], outstream: TextIO) -> None:
        """Answer each line of instream on outstream until the input ends."""
        ...

    def serve_line(self, line: str, outstream: TextIO) -> None:
        """Answer one JSON-RPC line on outstream."""
        ...


def git_event(repo: str | Path, words: list[str]) -> Event:
    """The event the git block's command is judged as: a git line in repo, as the git rules read one (HarnessGit: not
    a shell of the user's, so the shell reader asks nothing of it).

    Args:
        repo: the repository the command runs in.
        words: the words after git.

    Returns:
        A PreToolUse Event of the tool HarnessGit with the command line, its cwd repo.
    """
    return Event("PreToolUse", "HarnessGit", {"command": shlex.join(["git", *words])}, "", str(repo))


def commit_event(repo: str | Path, files: Iterable[str], message: str) -> Event:
    """The event a commit the harness is about to make is judged as (gear/translate/commit.py): its repository, its
    files (from the repository root) and its message.

    Args:
        repo: the repository of the commit.
        files: the files committed, from the repository root.
        message: the commit message.

    Returns:
        A PreToolUse Event of the tool HarnessCommit.
    """
    return Event("PreToolUse", "HarnessCommit", {"repo": str(repo), "files": list(files), "message": message}, "",
                 str(repo))


def ports_of(items: dict[str, Item], claude_dir: str | Path) -> dict[str, Any]:
    """Every port of SERVER_PORTS; one that costs a read is a callable, read when the action runs.

    Args:
        items: the items of the blocks by name.
        claude_dir: the home, the .claude folder.

    Returns:
        {port name: port}, in the order of SERVER_PORTS: the LedgerPort (plans, ledger), the items, and callables
        (verify_command, doctor, git_judge: GitJudge, session, commit_judge: CommitJudge, banned, store, units: the
        declared units by name as {repo, path, verify, base}, github: call(method, path, fields) of GitHub REST, limits:
        the orchestra limits {children, rounds} of the config, judge).
    """
    ledger = LedgerPort(claude_dir)
    ports = {"plans": ledger, "ledger": ledger, "verify_command": lambda: Config.load(claude_dir).verify,
             "items": items, "doctor": lambda: report(doctor(claude_dir)),
             "git_judge": lambda repo, words: build_runner(claude_dir, items).run(git_event(repo, words)).verdict,
             "session": ledger.session,
             "commit_judge": lambda repo, files, message: build_runner(claude_dir, items).run(
                 commit_event(repo, files, message)).verdict,
             "banned": lambda: Config.load(claude_dir).banned,
             "store": store.folder,
             "units": lambda: {name: unit.spec() for name, unit in Config.load(claude_dir).units},
             "github": github.call,
             "limits": lambda: dict(Config.load(claude_dir).limits),
             "judge": lambda event: build_runner(claude_dir, items).run(event).verdict}
    assert tuple(ports) == SERVER_PORTS, "ports_of builds exactly SERVER_PORTS"
    return ports


def action_table(items: dict[str, Item], code_dir: Optional[str | Path] = None) -> Any:
    """The actions run can reach: every entry of the action files of code_dir (the tree whose code runs).

    Args:
        items: the items of the blocks by name (action_table names the table's class).
        code_dir: the code folder whose action files are read; None: the code of the home that runs.

    Returns:
        The mcp ActionTable (mcp/actions/table.py, loaded by name) with every action class added.
    """
    table = Loader.resolve(items["action_table"])()
    for action_file in Loader(code_dir or code_of(CLAUDE_DIR)).action_files():
        for _, _, cls in Loader.actions(action_file):
            table.add(cls)
    return table


def build_server(claude_dir: str | Path) -> McpServer:
    """The MCP server of the home claude_dir, over the code that runs (code_of): find, guide and run.

    Args:
        claude_dir: the home, the .claude folder.

    Returns:
        The stdio server with the tools find, guide and run.
    """
    claude_dir = Path(claude_dir)
    items = items_of(claude_dir)
    table = action_table(items, code_of(claude_dir))
    skills = Loader.resolve(items["skills"])(skill_docs(claude_dir))
    ports = ports_of(items, claude_dir)
    tools = [Loader.resolve(items["find"])(skills, table), Loader.resolve(items["guide"])(skills, table, ports)]
    tools.append(Loader.resolve(items["run"])(table, ports))
    return Loader.resolve(items["stdio"])(*SERVER, tools)


def run_mcp(instream: Iterable[str], outstream: TextIO, claude_dir: str | Path = CLAUDE_DIR) -> None:
    """Serve find, guide and run over stdio until the input ends.

    Args:
        instream: the JSON-RPC lines in.
        outstream: where the answers go.
        claude_dir: the home, the .claude folder.
    """
    build_server(claude_dir).serve(instream, outstream)
