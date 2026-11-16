"""orchestra: the parent's side of a delegated plan (docs/05-orchestra.md, for the cloud as docs/05b-orchestra-cloud.md
says). The user approved the plan with its children once, in the form; these actions start the children.

- spawn {name, model?}: the brief of a child and the create_session call that opens it. Harness code cannot open a
  cloud session; the model does, then gives the new session id back with started.
- started {name, sid, model?}: the child's session is open; from now on it runs (the cap is 3).
- status: the children of the delegated plan in force and their states.

What a child does (take, ask, handback) and the parent's check, accept and reject come in the next parts."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from harness.utils.contracts import READ, WRITE, ActionContext, ActionError, McpAction
from harness.utils.git.facts import top
from harness.utils.git.run import GitError, git
from harness.utils.orchestra import brief as briefs
from harness.utils.orchestra import crew
from harness.utils.shapes import PlanStore

ACTIONS = [("orchestra.spawn", "Spawn"), ("orchestra.started", "Started"), ("orchestra.status", "Status")]
SESSION_ID = re.compile(r"^session_[A-Za-z0-9]{8,64}$")
NO_SESSION = "no session: the harness has not seen this session's prompt yet"
NAME_ARG = {"type": "string", "description": "the child's name, as its card names it"}


def session_of(ctx: ActionContext) -> str:
    """The session the action runs for: the parent.

    Args:
        ctx: the action's ports, with session (session() -> the session id the hook saw last).

    Returns:
        The Claude Code session id.

    Raises:
        ActionError: no session yet.
    """
    sid = ctx.ports["session"]()
    if not sid:
        raise ActionError(NO_SESSION)
    return sid


def source_url(root: str) -> str:
    """The URL a child clones: the origin of the repository holding the plan's root, without any user or token part;
    "" when there is none or it is not reachable from another machine (a local path or a loopback proxy).

    Args:
        root: the plan's root folder.

    Returns:
        The URL, or "".
    """
    try:
        repo = top(root) if root else None
        url = git(repo, "remote", "get-url", "origin").strip() if repo else ""
    except GitError:
        return ""
    url = re.sub(r"(?<=//)[^/@]*@", "", url)
    return url if re.match(r"^https://(?!127\.|localhost)", url) else ""


def room(port: PlanStore, sid: str, name: str) -> tuple[int, str, Any]:
    """The plan number, draft and card of a child the parent may start now.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.

    Returns:
        (plan number, desk id, Card).

    Raises:
        ActionError: the reason it may not start.
    """
    ticket = port.ticket(sid)
    try:
        card = crew.room(ticket, name)
    except ValueError as e:
        raise ActionError(str(e)) from e
    return ticket["plan"]["id"], ticket["draft"], card


class Spawn(McpAction):
    """orchestra.spawn: the brief of a child and the create_session call that opens it."""
    block, name, effect = "orchestra", "spawn", READ
    summary = ("Start a child of the delegated plan in force: the answer is its brief and the create_session call to "
               "make; then record it with started {name, sid}")
    args_schema = {"type": "object", "properties": {"name": NAME_ARG, "model": {"type": "string"}},
                   "required": ["name"]}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """The brief and the create_session call of the named child; nothing is written until started. ActionError
        when no approved delegated plan is in force, the name is no child of it, it has started, CAP children run, or
        its card names an open session to adopt."""
        sid = session_of(ctx)
        plan, draft, card = room(ctx.ports["plans"], sid, args["name"])
        if card.get("session"):
            raise ActionError(f"{card['name']}'s card names the session {card['session']!r} to adopt; adopting an open "
                              "session is not built yet: revise the card without session, or start it by hand")
        ticket = ctx.ports["plans"].ticket(sid)
        root = ticket["plan"].get("root") or os.getcwd()
        url = source_url(root)
        call = briefs.create_call(plan, card, briefs.brief(plan, draft, card, sid), url, args.get("model", ""))
        where = "" if url else (" The plan's repository has no origin another machine can clone: add source_url to "
                                "the call by hand.")
        return (f"Child {card['name']} of plan {plan}: open it with mcp__claude-code-remote__create_session and these "
                f"arguments, then record it at once: run('orchestra', 'started', {{name: '{card['name']}', sid: "
                f"<the new session id>}}). Until then it does not count as running. Each child is a cloud session "
                f"and costs as much as one.{where}\n" + json.dumps(call, ensure_ascii=False, indent=1))


class Started(McpAction):
    """orchestra.started: the child's cloud session is open; record it as running."""
    block, name, effect = "orchestra", "started", WRITE
    summary = "Record the session id create_session gave for a spawned child; from now on it runs"
    args_schema = {"type": "object", "properties": {"name": NAME_ARG, "sid": {"type": "string"},
                                                    "model": {"type": "string"}}, "required": ["name", "sid"]}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Write the child's crew entry (running, its session) and a story row in one transaction. ActionError for a
        session id of the wrong shape, this session's own id, a session that is another child already, or any reason
        spawn refuses."""
        sid = session_of(ctx)
        child_sid = str(args["sid"]).strip()
        if not SESSION_ID.match(child_sid):
            raise ActionError(f"{child_sid!r} is no session id: give the id create_session answered (session_...)")
        try:
            entry = ctx.ports["plans"].write(lambda con, rec: crew.start(con, sid, args["name"], child_sid,
                                                                         str(args.get("model") or "")))
        except ValueError as e:
            raise ActionError(str(e)) from e
        ticket = ctx.ports["plans"].ticket(sid)
        return (f"Child {args['name']} runs in session {entry['sid']} ({len(crew.running(ticket))} of {crew.CAP} "
                "running). It hands back by itself and tells you with send_message; do not poll it.")


class Status(McpAction):
    """orchestra.status: the children of the delegated plan in force."""
    block, name, effect = "orchestra", "status", READ
    summary = "The children of the delegated plan in force: each one's unit, state, rounds and session"
    args_schema = {"type": "object", "properties": {}}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """The status of the session's delegated plan (utils/orchestra/crew.status)."""
        return crew.status(ctx.ports["plans"].ticket(session_of(ctx)))

