"""orchestra: the parent's side of a delegated plan (docs/05-orchestra.md, for the cloud as docs/05b-orchestra-cloud.md
says). The user approved the plan with its children once, in the form; these actions start the children.

- spawn {name, model?}: the brief of a child and the create_session call that opens it. Harness code cannot open a
  cloud session; the model does, then gives the new session id back with started.
- started {name, sid, model?}: the child's session is open; from now on it runs (the cap is 3).
- status: the children of the delegated plan in force and their states.

A child (a session opened from a brief, utils/orchestra/child.py) runs the rest (utils/orchestra/work.py):
- take: its card plan opens, approved by the parent's grant, on its branch orch/p<plan>/<name>;
- push: its own branch, after every step;
- question {question}: kept, then sent to the parent with send_message;
- handback {changed, checked, notChecked, risks, testsChanged, added?, faults?}: the receipt on its branch, pushed.

The parent's check, accept and reject come in part 3."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from harness.utils.contracts import READ, WRITE, ActionContext, ActionError, McpAction
from harness.utils.git.facts import top
from harness.utils.git.run import GitError, git
from harness.utils.orchestra import brief as briefs
from harness.utils.orchestra import crew, work
from harness.utils.orchestra.card import unit_spec
from harness.utils.shapes import PlanStore

ACTIONS = [("orchestra.spawn", "Spawn"), ("orchestra.started", "Started"), ("orchestra.status", "Status"),
           ("orchestra.take", "Take"), ("orchestra.push", "Push"), ("orchestra.question", "Question"),
           ("orchestra.handback", "Handback")]
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
    needs = ("plans", "session", "units")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """The brief and the create_session call of the named child; nothing is written until started. ActionError
        when no approved delegated plan is in force, the name is no child of it, it has started, CAP children run, or
        its card names no change paths or an open session to adopt."""
        sid = session_of(ctx)
        plan, draft, card = room(ctx.ports["plans"], sid, args["name"])
        if not card.get("change"):
            raise ActionError(f"{card['name']}'s card names no files to change: a cloud child's plan is made from its "
                              "change paths; revise the card with change")
        if card.get("session"):
            raise ActionError(f"{card['name']}'s card names the session {card['session']!r} to adopt; adopting an open "
                              "session is not built yet: revise the card without session, or start it by hand")
        ticket = ctx.ports["plans"].ticket(sid)
        unit = unit_spec(card, ctx.ports.get("units", dict)())
        url = unit["repo"] or source_url(ticket["plan"].get("root") or os.getcwd())
        call = briefs.create_call(plan, card, briefs.brief(plan, draft, card, sid, unit), url, args.get("model", ""))
        where = "" if url else (" The unit's repository has no URL another machine can clone: add source_url to "
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



def child_run(step: Any) -> str:
    """Run one step of a child's work, its refusal turned into the action's error.

    Args:
        step: a callable with no argument that returns the answer (utils/orchestra/work.py).

    Returns:
        The step's answer.

    Raises:
        ActionError: the step refused (WorkError), or git failed.
    """
    try:
        return step()
    except (work.WorkError, GitError) as e:
        raise ActionError(str(e)) from e


class Take(McpAction):
    """orchestra.take: a child opens its card plan."""
    block, name, effect = "orchestra", "take", WRITE
    summary = ("A child's first call: its card plan opens, approved by the grant of the parent plan (no form), on its "
               "branch orch/p<plan>/<name>")
    args_schema = {"type": "object", "properties": {}}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Open the child's card plan in the server's folder (utils/orchestra/work.take). ActionError for a session that
        is no child, a card without change paths, another plan in force, or git refusing the branch."""
        sid = session_of(ctx)
        return child_run(lambda: work.take(ctx.ports["plans"], sid, os.getcwd()))


class Push(McpAction):
    """orchestra.push: a child pushes its own branch."""
    block, name, effect = "orchestra", "push", WRITE
    summary = "A child pushes its own branch to origin, after every step (its machine is temporary)"
    args_schema = {"type": "object", "properties": {}}
    needs = ("plans", "session", "git_judge")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Push the child's branch (utils/orchestra/work.push). ActionError for a session that is no child, no card
        plan, another branch checked out, a git rule that stops it, or git failing."""
        sid = session_of(ctx)
        return child_run(lambda: work.push(ctx.ports["plans"], sid, ctx.ports["git_judge"]))


class Question(McpAction):
    """orchestra.question: a child's question for its parent."""
    block, name, effect = "orchestra", "question", WRITE
    summary = "A child's question outside its card: kept, and the answer says what to send the parent with send_message"
    args_schema = {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Keep the question on the child's ticket (utils/orchestra/work.ask). ActionError for a session that is no
        child, or a question empty or longer than 400 characters."""
        sid = session_of(ctx)
        return child_run(lambda: work.ask(ctx.ports["plans"], sid, args["question"]))


class Handback(McpAction):
    """orchestra.handback: a child's report, kept as a receipt on its branch."""
    block, name, effect = "orchestra", "handback", WRITE
    summary = ("A child's last call: its report (changed, checked, notChecked, risks, testsChanged, added?, faults?) "
               "and what the harness reads (commits, verify, behaviours) written on its branch and pushed")
    points = {"type": "array", "items": {"type": "string"}}
    pairs = {"type": "array", "items": {"type": "object"}}
    args_schema = {"type": "object", "properties": {"changed": points, "checked": points, "notChecked": points,
                                                    "risks": points, "testsChanged": pairs, "added": pairs,
                                                    "faults": pairs},
                   "required": ["changed", "checked", "notChecked", "risks", "testsChanged"]}
    needs = ("plans", "session", "commit_judge", "git_judge")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Write, commit and push the child's receipt (utils/orchestra/work.handback). ActionError for a bad report, a
        session that is no child, no card plan, another branch, or a rule that stops the commit or the push."""
        sid = session_of(ctx)
        return child_run(lambda: work.handback(ctx.ports["plans"], sid, args, ctx.ports["commit_judge"],
                                               ctx.ports["git_judge"]))
