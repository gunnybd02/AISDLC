"""orchestra: the parent's side of a delegated plan (docs/05-orchestra.md, for the cloud as docs/05b-orchestra-cloud.md
says). The user approved the plan with its children once, in the form; these actions start the children.

- lock: the acceptance tests the cards name (acTests), written by the parent, committed and pushed on the plan branch
  plan/p<n>, their hashes kept (utils/orchestra/locked.py); spawn needs it for a card with acTests.
- spawn {name, model?}: the brief of a child and the create_session call that opens it. Harness code cannot open a
  cloud session; the model does, then gives the new session id back with started.
- started {name, sid, model?}: the child's session is open; from now on it runs (the cap is 3).
- status: the children of the delegated plan in force and their states.

A child (a session opened from a brief, utils/orchestra/child.py) runs the rest (utils/orchestra/work.py):
- take: its card plan opens, approved by the parent's grant, on its branch orch/p<plan>/<name>;
- push: its own branch, after every step;
- question {question}: a note on its branch, pushed; then it stops;
- handback {changed, checked, notChecked, risks, testsChanged, added?, faults?}: the receipt on its branch, pushed.

Parent and child talk through the child's branch, never by message (utils/orchestra/work.py).

The parent's check, accept and reject come in part 3."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from harness.utils.contracts import ActionContext, ActionError, McpAction, READ, WRITE, answered, session_of
from harness.utils.git.facts import top
from harness.utils.git.run import GitError, git
from harness.utils.orchestra import brief as briefs
from harness.utils.orchestra import crew, locked, work
from harness.utils.orchestra.card import in_force, plan_units, unit_spec
from harness.utils.plan.item_checks import run_limits
from harness.utils.shapes import PlanStore

ACTIONS = [("orchestra.lock", "Lock"), ("orchestra.spawn", "Spawn"), ("orchestra.started", "Started"),
           ("orchestra.status", "Status"),
           ("orchestra.take", "Take"), ("orchestra.push", "Push"), ("orchestra.question", "Question"),
           ("orchestra.handback", "Handback")]
CHILD_ERRORS = (work.WorkError, GitError)  # the refusals of its steps, answered as the action's error
SESSION_ID = re.compile(r"^session_[A-Za-z0-9]{8,64}$")
NAME_ARG = {"type": "string", "description": "the child's name, as its card names it"}


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


def room(port: PlanStore, sid: str, name: str, cap: int) -> tuple[int, str, Any]:
    """The plan number, draft and card of a child the parent may start now.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        cap: the children that may run at once (the config's limits.children).

    Returns:
        (plan number, desk id, Card).

    Raises:
        ActionError: the reason it may not start.
    """
    ticket = port.ticket(sid)
    try:
        card = crew.room(ticket, name, cap)
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
    needs = ("plans", "session", "units", "limits")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """The brief and the create_session call of the named child; nothing is written until started. A child that
        waits for a fresh session (a note on its branch) gets the brief of a fresh session. ActionError when no approved
        delegated plan is in force, the name is no child of it, it has started, limits.children run, or its card names no
        change paths or an open session to adopt."""
        sid = session_of(ctx)
        own = in_force(ctx.ports["plans"], sid)
        limits = run_limits(own, ctx.ports["limits"]())
        plan, draft, card = room(ctx.ports["plans"], sid, args["name"], limits["children"])
        if not card.get("change"):
            raise ActionError(f"{card['name']}'s card names no files to change: a cloud child's plan is made from its "
                              "change paths; revise the card with change")
        if card.get("session"):
            raise ActionError(f"{card['name']}'s card names the session {card['session']!r} to adopt; adopting an open "
                              "session is not built yet: revise the card without session, or start it by hand")
        ticket = ctx.ports["plans"].ticket(sid)
        waiting = locked.unlocked(ticket, card)
        if waiting:
            raise ActionError(f"{card['name']}'s acceptance tests are not locked yet ({', '.join(waiting)}): write them, "
                              "then run('orchestra', 'lock', {}) before any child starts")
        unit = unit_spec(card, plan_units(own, ctx.ports["units"]()))
        url = unit["repo"] or source_url(ticket["plan"].get("root") or os.getcwd())
        fresh = ((ticket.get("crew") or {}).get(card["name"]) or {}).get("fresh") or {}
        start = (ticket.get(locked.LOCK) or {}).get("branch", "")  # with a lock, every child starts from the plan branch
        prompt = briefs.brief(plan, draft, card, sid, unit, fresh.get("note", ""), rounds=limits["rounds"], start=start)
        call = briefs.create_call(plan, card, prompt, url, args.get("model", ""))
        where = "" if url else (" The unit's repository has no URL another machine can clone: add source_url to "
                                "the call by hand.")
        return (f"Child {card['name']} of plan {plan}: open it with mcp__claude-code-remote__create_session and these "
                f"arguments, then record it at once: run('orchestra', 'started', {{name: '{card['name']}', sid: "
                f"<the new session id>}}). Until then it does not count as running. Each child is a cloud session "
                f"and costs as much as one.{where}\n" + json.dumps(call, ensure_ascii=False, indent=1))


class Lock(McpAction):
    """orchestra.lock: the acceptance tests of the cards, committed and pushed on the plan branch, their hashes kept."""
    block, name, effect = "orchestra", "lock", WRITE
    summary = ("Lock the acceptance tests the cards name (acTests, written by you first): commit them on the plan "
               "branch plan/p<n> and push it, before any child starts; spawn needs it")
    args_schema = {"type": "object", "properties": {}}
    needs = ("plans", "session", "units")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Lock the acceptance tests of the delegated plan in force (utils/orchestra/locked.py). ActionError for no
        delegated plan, no card with acTests, a started child, a test not written yet, or a push that fails."""
        sid = session_of(ctx)
        units = plan_units(in_force(ctx.ports["plans"], sid), ctx.ports["units"]())
        try:
            return locked.lock(ctx.ports["plans"], sid, units)
        except locked.LockError as e:
            raise ActionError(str(e)) from e


class Started(McpAction):
    """orchestra.started: the child's cloud session is open; record it as running."""
    block, name, effect = "orchestra", "started", WRITE
    summary = "Record the session id create_session gave for a spawned child; from now on it runs"
    args_schema = {"type": "object", "properties": {"name": NAME_ARG, "sid": {"type": "string"},
                                                    "model": {"type": "string"}}, "required": ["name", "sid"]}
    needs = ("plans", "session", "limits")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Write the child's crew entry (running, its session) and a story row in one transaction. ActionError for a
        session id of the wrong shape, this session's own id, a session that is another child already, or any reason
        spawn refuses."""
        sid = session_of(ctx)
        cap = run_limits(in_force(ctx.ports["plans"], sid), ctx.ports["limits"]())["children"]
        child_sid = str(args["sid"]).strip()
        if not SESSION_ID.match(child_sid):
            raise ActionError(f"{child_sid!r} is no session id: give the id create_session answered (session_...)")
        first = not ((ctx.ports["plans"].ticket(sid) or {}).get("crew"))  # no child started before this one
        try:
            entry = ctx.ports["plans"].write(lambda con, rec: crew.start(con, sid, args["name"], child_sid, cap,
                                                                         str(args.get("model") or "")))
        except ValueError as e:
            raise ActionError(str(e)) from e
        ticket = ctx.ports["plans"].ticket(sid)
        checkin = (" This is the first child: set a check-in now, since no child messages you: "
                   "mcp__claude-code-remote__send_later {\"delay_minutes\": 30, \"message\": \"Orchestra check-in: "
                   "run('orchestra', 'check', {name}) for each running child (it reads the child's branch: a receipt or "
                   "a question), and set the next check-in while a child still runs.\"}.") if first else ""
        return (f"Child {args['name']} runs in session {entry['sid']} ({len(crew.running(ticket))} of {cap} "
                "running). It talks only through its branch: it pushes its receipt, or a question, and stops; it "
                "sends no message. To look at it, run('orchestra', 'check', {name}): it reads the branch and "
                f"says whether the child handed back, asked a question, or is still working.{checkin}")


class Status(McpAction):
    """orchestra.status: the children of the delegated plan in force."""
    block, name, effect = "orchestra", "status", READ
    summary = "The children of the delegated plan in force: each one's unit, state, rounds and session"
    args_schema = {"type": "object", "properties": {}}
    needs = ("plans", "session", "limits")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """The status of the session's delegated plan (utils/orchestra/crew.status)."""
        sid = session_of(ctx)
        cap = run_limits(in_force(ctx.ports["plans"], sid), ctx.ports["limits"]())["children"]
        return crew.status(ctx.ports["plans"].ticket(sid), cap)



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
        return answered(CHILD_ERRORS, lambda: work.take(ctx.ports["plans"], sid, os.getcwd()))


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
        return answered(CHILD_ERRORS, lambda: work.push(ctx.ports["plans"], sid, ctx.ports["git_judge"]))


class Question(McpAction):
    """orchestra.question: a child's question for its parent."""
    block, name, effect = "orchestra", "question", WRITE
    summary = "A child's question outside its card: a note on its branch, pushed; then the child stops"
    args_schema = {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}
    needs = ("plans", "session", "commit_judge", "git_judge")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Commit the question as a note on the child's branch and push it (utils/orchestra/work.ask). ActionError for
        a session that is no child, a question empty or longer than 400 characters, no card plan, another branch, or a
        rule that stops the commit or the push."""
        sid = session_of(ctx)
        return answered(CHILD_ERRORS, lambda: work.ask(ctx.ports["plans"], sid, args["question"], ctx.ports["commit_judge"],
                                           ctx.ports["git_judge"]))


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
    needs = ("plans", "session", "commit_judge", "git_judge", "store")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Write, commit and push the child's receipt (utils/orchestra/work.handback). ActionError for a bad report, a
        session that is no child, no card plan, another branch, or a rule that stops the commit or the push."""
        sid = session_of(ctx)
        return answered(CHILD_ERRORS, lambda: work.handback(ctx.ports["plans"], sid, args, ctx.ports["commit_judge"],
                                               ctx.ports["git_judge"], bool(ctx.ports["store"]())))
