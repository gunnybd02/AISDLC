"""The harness's MCP tools from a terminal: python3 <home>/entry/boot.py cli tool find|guide|run ... It is for a session
whose Claude Code did not load the harness's MCP server (a cloud session can start Claude before its setup script
installs the server). It is the same server (wire_mcp.build_server): the same actions, ports and judge, so a write
action is judged by the same rule rows. The session is the one whose shell the hook last saw run the harness
(runner.py touches it), as for the MCP server.

- tool find <words...> [--mode skills|mcp]
- tool guide <name> [--mode mcp|skills] [--topic <action>]
- tool run <block> <action> ['<args as a JSON object>']"""
import json

from harness.assemble.engine.wire_mcp import build_server


def add_parser(doors):
    tool = doors.add_parser("tool", exit_on_error=False).add_subparsers(dest="tool", required=True)
    find = tool.add_parser("find", exit_on_error=False)
    find.add_argument("query", nargs="+")
    find.add_argument("--mode", choices=("skills", "mcp"))
    guide = tool.add_parser("guide", exit_on_error=False)
    guide.add_argument("name")
    guide.add_argument("--mode", choices=("skills", "mcp"), default="mcp")
    guide.add_argument("--topic")
    run = tool.add_parser("run", exit_on_error=False)
    run.add_argument("block")
    run.add_argument("action")
    run.add_argument("args", nargs="?", default="{}")


def arguments(args):
    """The arguments of the tool call the command line names; ValueError when they are not an object."""
    if args.tool == "find":
        return {"query": " ".join(args.query), **({"mode": args.mode} if args.mode else {})}
    if args.tool == "guide":
        return {"name": args.name, "mode": args.mode, **({"topic": args.topic} if args.topic else {})}
    try:
        given = json.loads(args.args)
    except ValueError as e:
        raise ValueError(f"the action's args are not JSON: {e}") from e
    if not isinstance(given, dict):
        raise ValueError("the action's args are a JSON object, such as '{\"plan\": \"pd-1\"}'")
    return {"block": args.block, "action": args.action, "args": given}


def tool_door(args, claude_dir):
    """(exit code, text): 0 the tool answered, 1 it answered an error."""
    call = arguments(args)
    try:
        result = build_server(claude_dir).tools[args.tool].call(call)
    except Exception as e:  # as the MCP server answers a tool that fails
        return 1, f"{args.tool} failed: {type(e).__name__}: {e}"
    return (1 if result.is_error else 0), result.text
