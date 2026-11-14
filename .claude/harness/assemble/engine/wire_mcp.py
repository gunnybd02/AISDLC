"""The MCP door entry/mcp_server.py calls: run_mcp serves find, guide and run, over the action table. The actions are
the classes of the ACTIONS literals of mcp/actions/*.py; the ports are SERVER_PORTS (engine/ports.py), built here, and
run hands each action only those it names in needs. The judge port is the hook's own runner: a write action is judged
by the same rules as a tool call."""
import shlex
from pathlib import Path

from harness.assemble.engine.build import CLAUDE_DIR, build_runner, items_of
from harness.assemble.engine.checks import doctor, report
from harness.assemble.engine.config import Config
from harness.assemble.engine.loader import Loader
from harness.assemble.engine.ports import SERVER_PORTS, LedgerPort
from harness.utils.contracts import Event

SERVER = ("harness", "0.1")


def git_event(repo, words):
    """The event the git block's command is judged as: a git line in repo, as the git rules read one (HarnessGit: not
    a shell of the user's, so the shell reader asks nothing of it)."""
    return Event("PreToolUse", "HarnessGit", {"command": shlex.join(["git", *words])}, "", str(repo))


def commit_event(repo, files, message):
    """The event a commit the harness is about to make is judged as (gear/translate/commit.py): its repository, its
    files (from the repository root) and its message."""
    return Event("PreToolUse", "HarnessCommit", {"repo": str(repo), "files": list(files), "message": message}, "",
                 str(repo))


def ports_of(items, claude_dir):
    """Every port of SERVER_PORTS; one that costs a read is a callable, read when the action runs."""
    ledger = LedgerPort(claude_dir)
    ports = {"plans": ledger, "ledger": ledger, "verify_command": lambda: Config.load(claude_dir).verify,
             "items": items, "doctor": lambda: report(doctor(claude_dir)),
             "git_judge": lambda repo, words: build_runner(claude_dir, items).run(git_event(repo, words)).verdict,
             "session": ledger.session,
             "commit_judge": lambda repo, files, message: build_runner(claude_dir, items).run(
                 commit_event(repo, files, message)).verdict,
             "judge": lambda event: build_runner(claude_dir, items).run(event).verdict}
    assert tuple(ports) == SERVER_PORTS, "ports_of builds exactly SERVER_PORTS"
    return ports


def action_table(items, code_dir=CLAUDE_DIR):
    """The actions run can reach: every entry of the action files of code_dir (the tree whose code runs)."""
    table = Loader.resolve(items["action_table"])()
    for action_file in Loader(code_dir).action_files():
        for _, _, cls in Loader.actions(action_file):
            table.add(cls)
    return table


def run_mcp(instream, outstream, claude_dir=CLAUDE_DIR):
    """Serve find, guide and run over stdio until the input ends."""
    claude_dir = Path(claude_dir)
    items = items_of(claude_dir)
    table = action_table(items, claude_dir)
    skills = Loader.resolve(items["skills"])(claude_dir / "project" / "skills")
    tools = [Loader.resolve(items[n])(skills, table) for n in ("find", "guide")]
    tools.append(Loader.resolve(items["run"])(table, ports_of(items, claude_dir)))
    Loader.resolve(items["stdio"])(*SERVER, tools).serve(instream, outstream)
