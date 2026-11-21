"""orchestra: the parent's side of a delegated plan (docs/05-orchestra.md, for the cloud as docs/05b-orchestra-cloud.md
says). The user approved the plan with its children once, in the form; these actions start the children.

- lock: the acceptance tests the cards name (acTests), written by the parent, their text and hashes kept in the
  ledger (utils/orchestra/locked.py); each child's start commit adds them; spawn needs it for a card with acTests.
- tickets: one GitHub issue per child with a machine block and its hash, and the ticket file (utils/orchestra/issues.py).
- spawn {name, model?}: the brief of a child and the create_session call that opens it, on Sonnet unless a model is
  named (another model asks the user's form: utils/forge/sessions.py). Harness code cannot open a cloud session; the
  model does, then gives the new session id back with started.
- started {name, sid, model?}: the child's session is open; from now on it runs (the cap is 3).
- status: the children of the delegated plan in force and their states.

A child (a session opened from a brief, utils/orchestra/child.py) runs the rest (utils/orchestra/work.py):
- take: its card plan opens, approved by the parent's grant, on its branch orch/p<plan>/<name>;
- push: its own branch, after every step;
- question {question}: a comment on its draft and an empty commit, pushed; then it stops;
- handback {changed, checked, notChecked, risks, testsChanged, added?, faults?}: its report and receipt as a comment
  on its draft, and an empty commit, pushed.

Parent and child talk in comments on the child's draft, never by message (utils/orchestra/talk.py).

The parent's check, accept and reject come in part 3."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from harness.utils.contracts import ActionContext, ActionError, McpAction, READ, WRITE, answered, session_of
from harness.utils.git.facts import top
from harness.utils.git.run import GitError, git
from harness.utils.ledger import layout, store
from harness.utils.orchestra import brief as briefs
from harness.utils.orchestra import crew, issues, locked, orders, register, work
from harness.utils.orchestra import draft as drafts  # draft is also the desk id of a plan here
from harness.utils.orchestra.card import in_force, plan_units, unit_spec
from harness.utils.plan.item_checks import run_limits
from harness.utils.shapes import PlanStore, Ticket

ACTIONS = [("orchestra.lock", "Lock"), ("orchestra.tickets", "Tickets"), ("orchestra.spawn", "Spawn"),
           ("orchestra.started", "Started"),
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
    block, name, effect = "orchestra", "spawn", WRITE
    summary = ("Start a child of the delegated plan in force: the answer is its brief and the create_session call to "
               "make (first the watch of its draft pull request); then record it with started")
    args_schema = {"type": "object", "properties": {"name": NAME_ARG, "model": {"type": "string"}},
                   "required": ["name"]}
    needs = ("plans", "session", "units", "limits", "github")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """The brief and the create_session call of the named child. Its draft pull request is opened first, once
        (utils/orchestra/draft.py), and the answer gives the call that watches it. A child that waits for a
        fresh session (a note on its branch) gets the brief of a fresh session. ActionError when no approved delegated
        plan is in force, the name is no child of it, it has started, limits.children run, its card names no change
        paths or an open session to adopt, or the draft cannot be opened."""
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
        start = ""  # no plan branch: every child starts from its unit's base, its tests in its start commit
        issue, made = self.recorded(ctx.ports["plans"], ticket, card["name"]) if ticket.get(locked.LOCK) else ({}, {})
        try:  # the draft comes first, for every child: the brief names it, and the talk goes there (talk.py)
            pr = drafts.open_draft(ctx.ports["plans"], sid, card, unit, ctx.ports["github"])
        except drafts.DraftError as e:
            raise ActionError(str(e)) from e
        watch = (f"First watch its draft pull request #{pr['number']} ({pr['url']}), so a CI result of any push "
                 f"wakes you: {drafts.WATCH} {json.dumps(drafts.watch_call(pr))}. Then ")
        prompt = briefs.brief(plan, draft, card, sid, unit, fresh.get("note", ""), rounds=limits["rounds"], start=start,
                              issue=issue, ticket_file=made, pr=pr, cloud=briefs.cloud_id(),
                              key=orders.key_for(ctx.ports["plans"], sid, card["name"]),
                              locks={p: h for p, h in locked.locked_files(ticket).items()
                                     if p in card.get("acTests", [])},  # the child's harness refuses a drifted test
                              store_path=layout.run_path(ticket["plan"], card["name"]))  # where its stop copy goes
        call = briefs.create_call(plan, card, prompt, url, args.get("model", ""))
        where = "" if url else (" The unit's repository has no URL another machine can clone: add source_url to "
                                "the call by hand.")
        return (f"{watch}Child {card['name']} of plan {plan}: open it with mcp__claude-code-remote__create_session and these "
                f"arguments, then record it at once: run('orchestra', 'started', {{name: '{card['name']}', sid: "
                f"<the new session id>, model: '{call['model']}'}}). Until then it does not count as running. Each "
                f"child is a cloud session and costs as much as one on its model.{where}\n"
                + json.dumps(call, ensure_ascii=False, indent=1))

    @staticmethod
    def recorded(port: PlanStore, ticket: Ticket, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """The issue of a child and its ticket file: a plan with locked tests starts a child only with both.

        Args:
            port: the ledger port.
            ticket: the parent's ticket.
            name: the child's name.

        Returns:
            (its issue {repo, number, url, sha}, its ticket file {title, sha256, path}).

        Raises:
            ActionError: no issue yet; or, with a store folder, the ticket file is not in the store yet.
        """
        held = ticket.get(issues.ISSUES) or {}
        issue = (held.get("children") or {}).get(name)
        if not issue:
            raise ActionError(f"{name} has no issue yet: run('orchestra', 'tickets', {{}}) after lock, then spawn")
        made = (held.get("files") or {}).get(name) or {}
        if store.folder() and not store.ticket_held(port, made.get("title", "")):
            raise ActionError(f"the ticket file {made.get('title') or '(not written)'} is not in the store yet: upload "
                              "it as run('orchestra', 'tickets', {}) said; the harness reads Drive's answer itself")
        return dict(issue), dict(made)


class Lock(McpAction):
    """orchestra.lock: the acceptance tests of the cards, their text and hashes kept in the ledger; nothing pushed."""
    block, name, effect = "orchestra", "lock", WRITE
    summary = ("Lock the acceptance tests the cards name (acTests, written by you first): keep their text and hashes "
               "in the ledger, before any child starts; spawn needs it. Each child's start commit adds them; nothing "
               "is pushed and no CI file is written")
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


class Tickets(McpAction):
    """orchestra.tickets: one GitHub issue per child, and the ticket file of the delegated plan."""
    block, name, effect = "orchestra", "tickets", WRITE
    summary = ("Open one GitHub issue per child of the delegated plan (after lock, before spawn), each with its card and "
               "a machine block with its hash, then write each child's ticket file (its CSV row) and give the Drive "
               "calls that upload it into its subtask folder of the store; a second call opens no issue again")
    args_schema = {"type": "object", "properties": {"into": {"type": "string"}}}
    needs = ("plans", "session", "units", "github")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Open the issues and write the ticket file (utils/orchestra/issues.py) into <into>/.harness-export/ (the
        working folder by default). ActionError for no delegated plan, a started child, a unit with no repository URL,
        GitHub refusing, or into not a folder."""
        sid, port = session_of(ctx), ctx.ports["plans"]
        units = plan_units(in_force(port, sid), ctx.ports["units"]())
        into = str(args.get("into") or os.getcwd())  # the Drive tool reads files only from the session's own folders
        if not os.path.isdir(into):
            raise ActionError(f"into is a folder of this session's working folder; {into} is not a folder")
        try:
            lines = issues.open_issues(port, sid, units, ctx.ports["github"])
            files = issues.write_ticket(port, sid, into)
        except issues.IssueError as e:
            raise ActionError(str(e)) from e
        plan = port.ticket(sid)["plan"]
        return "\n".join(lines + [issues.upload_words(port, sid, plan, files, store.folder(),
                                                      store.place(port, "tickets"))])


class Started(McpAction):
    """orchestra.started: the child's cloud session is open; record it as running."""
    block, name, effect = "orchestra", "started", WRITE
    summary = "Record the session id create_session gave for a spawned child; from now on it runs"
    args_schema = {"type": "object", "properties": {"name": NAME_ARG, "sid": {"type": "string"},
                                                    "model": {"type": "string"}}, "required": ["name", "sid"]}
    needs = ("plans", "session", "limits")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Write the child's crew entry (running, its session) and a story row in one transaction. ActionError for a
        session id of the wrong shape, this session's own id, a session that is another child already, a child of a
        plan with locked tests whose draft pull request is not watched yet (utils/orchestra/draft.py), or any reason
        spawn refuses."""
        sid = session_of(ctx)
        cap = run_limits(in_force(ctx.ports["plans"], sid), ctx.ports["limits"]())["children"]
        child_sid = str(args["sid"]).strip()
        if not SESSION_ID.match(child_sid):
            raise ActionError(f"{child_sid!r} is no session id: give the id create_session answered (session_...)")
        waiting = drafts.unwatched(ctx.ports["plans"].ticket(sid) or {}, str(args["name"]))
        if waiting:  # with locked tests, a CI result must wake this session from the child's first push
            raise ActionError(waiting)
        first = not ((ctx.ports["plans"].ticket(sid) or {}).get("crew"))  # no child started before this one
        try:
            entry = ctx.ports["plans"].write(lambda con, rec: crew.start(con, sid, args["name"], child_sid, cap,
                                                                         str(args.get("model") or "")))
        except ValueError as e:
            raise ActionError(str(e)) from e
        ticket = ctx.ports["plans"].ticket(sid)
        checkin = (" This is the first child: set a check-in now, since no child messages you: "
                   "mcp__claude-code-remote__send_later {\"delay_minutes\": 30, \"message\": \"Orchestra check-in: "
                   "run('orchestra', 'check', {name}) for each running child (it reads the child's draft: a handback or "
                   "a question comment), and set the next check-in while a child still runs.\"}.") if first else ""
        return (f"Child {args['name']} runs in session {entry['sid']} ({len(crew.running(ticket))} of {cap} "
                "running). It talks by comments its harness posts on its draft (a question, or its handback with the "
                "receipt), each with an empty commit that wakes you; it sends no message. To look at it, "
                "run('orchestra', 'check', {name}): it reads its draft and branch and "
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
    summary = ("A child's first call: it registers against its issue and ticket when its brief names them, then its "
               "card plan opens, approved by the grant of the parent plan (no form), on its branch orch/p<plan>/<name>")
    args_schema = {"type": "object", "properties": {}}
    needs = ("plans", "session", "github")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Register the child (utils/orchestra/register.check), then open its card plan in the server's folder
        (utils/orchestra/work.take), its registration posted first as a comment on its issue (register.on_issue): the
        branch holds no file of it. ActionError for a ticket not checked yet, records that disagree with the brief, a
        session that is no child, a card without change paths, another plan in force, git refusing the branch, or
        GitHub refusing the registration's comment."""
        sid, port = session_of(ctx), ctx.ports["plans"]

        def go() -> str:
            line = register.check(port, sid, os.getcwd(), ctx.ports["github"])

            def first(repo: str) -> Optional[dict[str, Any]]:
                return register.on_issue(port, sid, ctx.ports["github"])
            return (line + "\n" if line else "") + work.take(port, sid, os.getcwd(), first)
        return answered(CHILD_ERRORS + (register.RegisterError,), go)


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
    summary = "A child's question outside its card: a comment on its draft with an empty commit, pushed; then it stops"
    args_schema = {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}
    needs = ("plans", "session", "commit_judge", "git_judge", "github")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Post the question on the child's draft with an empty signal commit and push it (utils/orchestra/work.ask).
        ActionError for a session that is no child, a question empty or longer than 400 characters, no card plan,
        another branch, no draft, a comment not posted, or a rule that stops the commit or the push."""
        sid, port = session_of(ctx), ctx.ports["plans"]
        return answered(CHILD_ERRORS, lambda: work.ask(port, sid, args["question"], ctx.ports["commit_judge"],
                                                       ctx.ports["git_judge"], ctx.ports["github"]))


class Handback(McpAction):
    """orchestra.handback: a child's report and receipt, a comment on its draft."""
    block, name, effect = "orchestra", "handback", WRITE
    summary = ("A child's last call: its report (changed, checked, notChecked, risks, testsChanged, added?, faults?) "
               "and what the harness reads (commits, verify, behaviours) posted on its draft, with an empty commit")
    points = {"type": "array", "items": {"type": "string"}}
    pairs = {"type": "array", "items": {"type": "object"}}
    args_schema = {"type": "object", "properties": {"changed": points, "checked": points, "notChecked": points,
                                                    "risks": points, "testsChanged": pairs, "added": pairs,
                                                    "faults": pairs},
                   "required": ["changed", "checked", "notChecked", "risks", "testsChanged"]}
    needs = ("plans", "session", "commit_judge", "git_judge", "store", "github")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Post the child's report and receipt on its draft with an empty signal commit, and push
        (utils/orchestra/work.handback). ActionError for a bad report, a session that is no child, no card plan,
        another branch, no draft, a comment not posted, or a rule that stops the commit or the push."""
        sid, port = session_of(ctx), ctx.ports["plans"]
        return answered(CHILD_ERRORS, lambda: work.handback(port, sid, args, ctx.ports["commit_judge"],
                                                            ctx.ports["git_judge"], ctx.ports["github"],
                                                            bool(ctx.ports["store"]())))
