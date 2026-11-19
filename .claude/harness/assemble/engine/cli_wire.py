"""The CLI doors (harness/entry/cli.py): verify, tool (the MCP tools from a terminal, cli_tool.py) and the doors that widen or
shrink the approved plan of a session (docs 04, sections 4 and 5). The session is --session, else HARNESS_SESSION, else
the last one the hook saw (tool: always that one, as for the MCP server). Each door answers
(exit code, text): 0 done, 1 refused. ci (utils/orchestra/ci.py) runs on the forge: it needs no session and opens no
ledger, and answers 1 when a rule fails."""
from __future__ import annotations

import argparse
import os
import shlex
from pathlib import Path

from harness.assemble.engine import cli_live, cli_tool
from harness.assemble.engine.ports import LedgerPort
from harness.utils.git.github import call as github_call
from harness.utils.git.run import GitError
from harness.utils.orchestra import ci
from harness.utils.plan import grants
from harness.utils.plan.verify import command_of as plan_command, MAX_TIMEOUT, VERIFY_TIMEOUT, run
from harness.utils.shapes import ApprovedPlan

SESSION_ENV = "HARNESS_SESSION"


class Refused(Exception):
    """A door will not do what it was asked; the message says why."""


def parser() -> argparse.ArgumentParser:
    """The CLI's parser: verify, add, live, behaviors and tool, each with --session.

    Returns:
        The top parser (it raises instead of exiting on an error).
    """
    top = argparse.ArgumentParser(prog="python3 anchor.py cli", exit_on_error=False)
    top.add_argument("--session", dest="top_session")
    doors = top.add_subparsers(dest="door", required=True)
    v = doors.add_parser("verify", exit_on_error=False)
    v.add_argument("--in", dest="folder")
    v.add_argument("--timeout", type=int, default=VERIFY_TIMEOUT)
    v.add_argument("--full", action="store_true")
    v.add_argument("--session")
    v.add_argument("command", nargs=argparse.REMAINDER)
    add = doors.add_parser("add", exit_on_error=False).add_subparsers(dest="what", required=True)
    for name, extra in (("file", ("--behavior", "--why")), ("test", ("--behavior", "--what_")),
                        ("drop-file", ("--why",)), ("retire-test", ("--why",))):
        sub = add.add_parser(name, exit_on_error=False)
        sub.add_argument("target")
        sub.add_argument("--session")
        for flag in extra:
            if flag == "--what_":
                sub.add_argument("--what", dest="what_", required=True)
            else:
                sub.add_argument(flag, required=True)
    live = doors.add_parser("live", exit_on_error=False).add_subparsers(dest="what", required=True)
    for name in ("status", "publish", "update", "hint"):
        live.add_parser(name, exit_on_error=False).add_argument("--session")
    beh = doors.add_parser("behaviors", exit_on_error=False).add_subparsers(dest="what", required=True)
    b_add = beh.add_parser("add", exit_on_error=False)
    b_add.add_argument("id")
    b_add.add_argument("--what", dest="what_", required=True)
    for flag in ("--how", "--why"):
        b_add.add_argument(flag, required=True)
    b_add.add_argument("--test", action="append", required=True)
    for name in ("list", "check", "retire"):
        sub = beh.add_parser(name, exit_on_error=False)
        sub.add_argument("--session")
        if name == "retire":
            sub.add_argument("id")
            sub.add_argument("--why", required=True)
        if name == "list":
            sub.add_argument("--log", action="store_true")
    for sub in (b_add,):
        sub.add_argument("--session")
    check = doors.add_parser("ci", exit_on_error=False)
    check.add_argument("--base", default="")
    check.add_argument("--head", default="")
    check.add_argument("--sha", default="")
    check.add_argument("--in", dest="folder")
    cli_tool.add_parser(doors)
    return top


def ci_door(args: argparse.Namespace) -> tuple[int, str]:
    """harness ci: the rules on a child's branch, from the repository and its issue alone (utils/orchestra/ci.py).

    Args:
        args: the parsed command line of the door ci: --base and --head (else GitHub Actions' GITHUB_BASE_REF and
            GITHUB_HEAD_REF), --sha the commit under test (else the head's tip on origin), --in the clone (else the
            current folder).

    Returns:
        (exit code, text): 0 when every rule passed, 1 when one failed. In GitHub Actions it also writes code=yes or
        code=no to GITHUB_OUTPUT (ci.has_code), which the workflow's test steps read.

    Raises:
        Refused: no base or head, or git cannot read the clone.
    """
    base = args.base or os.environ.get("GITHUB_BASE_REF", "")
    head = args.head or os.environ.get("GITHUB_HEAD_REF", "")
    if not base or not head:
        raise Refused("ci needs --base and --head (in GitHub Actions: GITHUB_BASE_REF and GITHUB_HEAD_REF)")
    folder = os.path.abspath(args.folder or ".")
    try:
        ok, text = ci.report(folder, base, head, github_call, args.sha)
    except GitError as e:
        raise Refused(f"git cannot read the clone: {str(e)[-300:]}") from e
    code = ci.has_code(folder, base, head, args.sha)  # the workflow's test steps run only when it is yes
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write(f"code={'yes' if code else 'no'}\n")
    text += "\nTests: " + ("they run." if code else "they wait: no commit past the start and the registration yet.")
    return (0 if ok else 1), text


def plan_of(port: LedgerPort, sid: str) -> ApprovedPlan:
    """The plan in force in the session.

    Args:
        port: the ledger port.
        sid: the session id ("" when none is known).

    Returns:
        The ApprovedPlan with its grants.

    Raises:
        Refused: no session, or no plan in force in it.
    """
    plan = port.approved(sid) if sid else None
    if plan is None:
        raise Refused("no approved plan in this session" + ("" if sid else " (no session: pass --session)"))
    return plan


def command_of(args: argparse.Namespace, claude_dir: str | Path) -> list[str]:
    """The test command a verify was given: the words after --; a plan with tests and no command of its own needs one.

    Args:
        args: the parsed command line of the door verify.
        claude_dir: the home (not read: no config names a command).

    Returns:
        The command's words.

    Raises:
        Refused: no words were given.
    """
    words = args.command[1:] if args.command[:1] == ["--"] else args.command
    if words:
        return list(words)
    raise Refused("the plan has tests and names no test command: add its repo with verify to the plan's repos, or "
                  "give a command after --")


def verify(port: LedgerPort, sid: str, args: argparse.Namespace, claude_dir: Path) -> tuple[int, str]:
    """Run the test command of the session's plan (utils/plan/verify.run) and keep its receipt.

    Args:
        port: the ledger port.
        sid: the session whose plan is verified.
        args: the parsed command line of the door verify (--in, --timeout, the command).
        claude_dir: the home, the .claude folder.

    Returns:
        (exit code, text): 0 green, 1 red; the text is the head line and the tail of the output.

    Raises:
        Refused: a timeout out of range, no plan in force, or no command.
    """
    if not 1 <= args.timeout <= MAX_TIMEOUT:
        raise Refused(f"--timeout is 1 to {MAX_TIMEOUT} seconds")
    plan = plan_of(port, sid)
    words = args.command[1:] if args.command[:1] == ["--"] else args.command
    command = list(words) if words else plan_command(plan, []) or command_of(args, claude_dir)
    folder = os.path.abspath(args.folder) if args.folder else plan["root"]
    ok, code, tail, files = run(port, plan, command, args.timeout, folder)
    proven = len([b for b in port.registry(plan).values() if b["status"] == "active"]) if ok else 0
    head = (f"Verify {'green' if ok else 'RED'} (exit {code}): {len(files)} changed file(s), {proven} behaviour(s) "
            f"proven. ({shlex.join(command)})")
    return (0 if ok else 1), "\n".join([head] + tail)


def run_cli(argv: list[str], claude_dir: str | Path) -> tuple[int, str]:
    """Run one CLI door: verify, tool, live, add or behaviors.

    Args:
        argv: the command line after cli.
        claude_dir: the home, the .claude folder.

    Returns:
        (exit code, text): 0 done, 1 refused (a refusal's text starts with "refused: ").
    """
    try:
        args = parser().parse_args(argv)
    except (argparse.ArgumentError, SystemExit) as e:
        return 1, f"refused: {e}"
    if args.door == "ci":  # on the forge: no session, no ledger
        try:
            return ci_door(args)
        except Refused as e:
            return 1, f"refused: {e}"
    port = LedgerPort(claude_dir)
    sid = getattr(args, "session", None) or args.top_session or os.environ.get(SESSION_ENV) or port.session()
    try:
        if args.door == "verify":
            return verify(port, sid, args, Path(claude_dir))
        if args.door == "tool":  # the session is the one the hook saw run this command, as for the MCP server
            return cli_tool.tool_door(args, Path(claude_dir))
        if args.door == "live":
            if args.what == "status":
                return 0, cli_live.status(Path(claude_dir))
            if args.what == "hint":
                return 0, cli_live.tools_hint(Path(claude_dir))
            door = cli_live.update_door if args.what == "update" else cli_live.publish_door
            return door(port, Path(claude_dir))
        plan = plan_of(port, sid)
        if args.door == "add":
            text = {"file": lambda: grants.add_file(port, sid, plan, args.target, args.behavior, args.why),
                    "test": lambda: grants.add_test(port, sid, plan, args.target, args.behavior, args.what_),
                    "drop-file": lambda: grants.drop_file(port, sid, plan, args.target, args.why),
                    "retire-test": lambda: grants.retire_test(port, sid, plan, args.target, args.why)}[args.what]()
            return 0, text
        if args.what == "add":
            return 0, grants.behaviors_add(port, sid, plan, args.id, args.what_, args.how, args.why, args.test)
        if args.what == "retire":
            return 0, grants.retire_test(port, sid, plan, args.id, args.why)
        if args.what == "list":
            return 0, grants.behaviors_list(port, plan)
        lines, gone = grants.behaviors_check(port, plan)
        return (1 if gone else 0), "\n".join(lines)
    except (Refused, grants.DoorError, ValueError) as e:
        return 1, f"refused: {e}"
