"""plan: present a plan as data; the user approves it in the form, and only its files may change (docs 04, section 2).
plan_present keeps a new desk plan, plan_revise a new revision of one with only the items that change, plan_drop
stops a waiting plan, plan_show and plan_status read one. Each needs the calling session."""
from __future__ import annotations

import os
from typing import Any

from harness.utils.contracts import ActionContext, ActionError, McpAction, READ, WRITE, session_of
from harness.utils.orchestra import child, crew
from harness.utils.plan import desk
from harness.utils.plan import render
from harness.utils.shapes import PlanItems, Revision

ACTIONS = [("plan.plan_present", "PlanPresent"), ("plan.plan_revise", "PlanRevise"), ("plan.plan_show", "PlanShow"),
           ("plan.plan_status", "PlanStatus"), ("plan.plan_drop", "PlanDrop")]
NOT_KEPT = "The plan was not kept: "


def declared(ctx: ActionContext) -> list[str]:
    """The names of the units project.json declares, for the services and children of a plan.

    Args:
        ctx: the action's ports, with units (units() -> {name: {repo, path, verify, base}}), declared in needs.

    Returns:
        The names; [] when no unit is declared.
    """
    return list(ctx.ports["units"]())


def answer(head: str, items: PlanItems, plan_id: str, rev: int, shown: str = "", form: bool = True,
           overview: bool = True) -> str:
    """The text for the model about a revision (docs 04 section 8): the head line, the instruction with the form call,
    the overview of a plan with no code (its block does not hold it), and the block in a text fence.

    Args:
        head: the first line (render.head for a waiting revision).
        items: the revision's items.
        plan_id: the desk id (pd-...).
        rev: the revision number.
        shown: the lines to show instead of the whole block (a revision's changed lines); "" for the block.
        form: False leaves the instruction and the form call out (the plan does not wait).
        overview: False leaves the overview of a plan with no code out (a revision that did not change it).

    Returns:
        The parts, separated by blank lines.
    """
    ask = (f"The user sees this answer in the tool row: do not repeat it. Write one line (the title and rev {rev}), "
           f"then the form, nothing after it. {render.form_call(items, plan_id, rev)}")
    above = [] if items.get("code") or not overview else render.overview_lines(items)
    return "\n\n".join([head] + ([ask] if form else []) + (["\n".join(above)] if above else [])
                       + [render.fenced(shown or render.block(items))])


def target(ctx: ActionContext, sid: str, args: dict[str, Any]) -> Revision:
    """The desk plan an action names, or the session's own: the newest waiting one, else its ticket's.

    Args:
        ctx: the action's ports, with plans (the ledger port, a PlanStore).
        sid: the calling session ("" when none).
        args: the action's arguments; plan names a desk id (pd-...) when given.

    Returns:
        The newest revision of that desk plan.

    Raises:
        ActionError: no such plan, or the session has none.
    """
    port, plan_id = ctx.ports["plans"], args.get("plan")
    if not plan_id:
        mine = [w for w in port.waiting() if w["sid"] == sid]
        plan_id = mine[-1]["plan_id"] if mine else (port.ticket(sid) or {}).get("draft")
    found = port.revision(plan_id) if plan_id else None
    if found is None:
        raise ActionError(f"no plan {plan_id}" if plan_id else "this session has no plan: present one")
    return found


class PlanPresent(McpAction):
    """plan.plan_present: a new desk plan, waiting for the user's approval."""
    block, name, effect = "plan", "plan_present", WRITE
    summary = ("Present a plan as data (title, what, files, tests; a full plan: steps, behaviors, checks, "
               "assumptions, notDoing, risks...); kept waiting for the user's approval in the form")
    args_schema = {"type": "object", "properties": {"plan": {"type": "object"}}, "required": ["plan"]}
    needs = ("plans", "session", "units")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Keep a new desk plan from the plan's data (cleaned, normalized, checked; its root the server's folder); answer
        its head line, the form call and its ## Plan block. ActionError in a child session, while a delegated plan runs in the
        session, for unknown keys or a plan that does not check."""
        sid, raw = session_of(ctx), args["plan"]
        ticket = ctx.ports["plans"].ticket(sid)
        busy = child.refusal(ticket, "never presents a plan of its own: its card plan opens with "
                                     "run('orchestra', 'take')") or crew.blocks_other(ticket)
        if busy:
            raise ActionError(NOT_KEPT + busy)
        items = desk.normalize(desk.clean(raw))
        problems = desk.unknown(raw) + desk.check(items, need_title=True, units=declared(ctx))
        if problems:
            raise ActionError(NOT_KEPT + "; ".join(problems))
        items["root"] = os.getcwd().replace("\\", "/")  # the MCP server runs in the project's folder
        plan_id, rev, _ = ctx.ports["plans"].present(items, sid=sid)
        return answer(render.head(items, plan_id, rev), items, plan_id, rev)


class PlanRevise(McpAction):
    """plan.plan_revise: a new revision of a desk plan with only the items that change."""
    block, name, effect = "plan", "plan_revise", WRITE
    summary = "Change a presented plan with only the items that change; the new revision waits for the form again"
    args_schema = {"type": "object", "properties": {"plan": {"type": "string"}, "changes": {"type": "object"},
                                                    "why": {"type": "object"}}, "required": ["plan", "changes"]}
    needs = ("plans", "session", "units")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Keep a new revision of the session's plan with only the items that change; answer its head line naming the
        changed items, the form call, and only the changed lines of the block. ActionError for another session's or an ended plan, record items of a running plan, a plan that
        does not check, or no change."""
        sid, port, changes = session_of(ctx), ctx.ports["plans"], args["changes"]
        old = port.revision(args["plan"])
        if old is None or old["sid"] not in (sid, ""):
            raise ActionError(f"no plan {args['plan']} of this session")
        if old["event"] in ("delivered", "dropped"):
            raise ActionError(f"plan {args['plan']} is {old['event']}: present a new plan")
        if desk.unknown(changes):
            raise ActionError(NOT_KEPT + "; ".join(desk.unknown(changes)))
        clean = desk.clean(changes)
        ticket = port.ticket(sid)
        running = bool(ticket and ticket.get("state") == "open" and ticket.get("draft") == args["plan"])
        record = set(desk.RECORD) - ({"title", "overview", "code"} if old["items"].get("code") else set())
        if running and set(clean) <= record | {"files", "tests"}:
            raise ActionError("the plan runs: record items go in the final report, and a file goes through add file; "
                              "a revision widens it (services, steps, behaviors, network, commands, children, branch, "
                              "what, commit, test, teamSkills)")
        root = old["items"].get("root")
        items = desk.normalize(desk.merge({k: v for k, v in old["items"].items() if k != "root"}, clean))
        problems = desk.check(items, need_title=False, keys=list(clean), units=declared(ctx))
        if problems:
            raise ActionError(NOT_KEPT + "; ".join(problems))
        items["root"] = root
        if items == old["items"]:
            raise ActionError("nothing changed")
        why = {k: v for k, v in (args.get("why") or {}).items() if k in clean}
        plan_id, rev, _ = port.present(items, plan_id=args["plan"], sid=sid, why=why)
        return answer(render.head(items, plan_id, rev, sorted(clean)), items, plan_id, rev,
                      shown=render.changed(old["items"], items) or "(no line of the block changed)",
                      overview="overview" in clean)


class PlanShow(McpAction):
    """plan.plan_show: the newest revision of a plan, as the user reads it."""
    block, name, effect = "plan", "plan_show", READ
    summary = "Show the newest revision of a plan as the user reads it, its state, and its form call while it waits"
    args_schema = {"type": "object", "properties": {"plan": {"type": "string"}}, "required": []}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Answer the newest revision of the named plan (or the session's) as the user reads it and its state; its
        form call too while it waits."""
        found = target(ctx, session_of(ctx), args)
        items, plan_id, rev = found["items"], found["plan_id"], found["rev"]
        if found["event"] == "waiting":
            return answer(render.head(items, plan_id, rev), items, plan_id, rev)
        return answer(f'"{items.get("title", "")}": plan {plan_id} rev {rev} (sha {found["sha"][:8]}) is '
                      f'{found["event"]}; it does not wait for an approval.', items, plan_id, rev, form=False)


class PlanStatus(McpAction):
    """plan.plan_status: the state of a plan and the session's ticket."""
    block, name, effect = "plan", "plan_status", READ
    summary = "A plan's revision, sha, state, revisions and feedback not answered yet; and this session's ticket"
    args_schema = {"type": "object", "properties": {"plan": {"type": "string"}}, "required": []}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Answer the named plan's (or the session's) revision, sha, state, revisions and unanswered feedback, and the
        session's ticket."""
        port, sid = ctx.ports["plans"], ctx.ports["session"]()
        lines = []
        try:
            found = target(ctx, sid, args) if sid or args.get("plan") else None
        except ActionError as e:
            found, lines = None, [str(e)]
        if found:
            ticket = port.ticket(found["sid"]) if found["sid"] else None
            state = {"waiting": "waiting", "dropped": "not waiting (dropped)", "delivered": "closed"}.get(
                found["event"], "approved" if ticket and ticket.get("draft") == found["plan_id"] else found["event"])
            notes = port.unread(found["plan_id"], found["at"])
            lines.append(f"Plan {found['plan_id']}: rev {found['rev']}, sha {found['sha'][:12]}, {state}, "
                         f"{found['revisions']} revision(s), {len(notes)} feedback not answered"
                         + "".join(f"\n- {n}" for n in notes))
        ticket = port.ticket(sid) if sid else None
        if ticket is None:
            return "\n".join(lines + ["This session has no ticket (phase prepare)."])
        plan = ticket.get("plan") or {}
        state = ticket["state"] + (f" ({ticket['closeReason']})" if ticket.get("closeReason") else "")
        lines.append(f"Ticket {ticket['id']}: {state}, phase {ticket['phase']}, plan {ticket.get('draft') or '-'} "
                     f"(no {plan.get('id', '-')}, rev {plan.get('rev', '-')}), commits {len(ticket['commits'])}")
        return "\n".join(lines)


class PlanDrop(McpAction):
    """plan.plan_drop: a waiting plan dropped."""
    block, name, effect = "plan", "plan_drop", WRITE
    summary = "Drop the plan waiting for approval; its revisions stay in the ledger"
    args_schema = {"type": "object", "properties": {"plan": {"type": "string"}}, "required": []}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Drop the session's (or the named) waiting plan; answer that it is dropped. ActionError when it does not wait."""
        sid = session_of(ctx)
        found = target(ctx, sid, args)
        if found["event"] != "waiting":
            raise ActionError(f"plan {found['plan_id']} does not wait for an approval ({found['event']})")
        ctx.ports["plans"].drop(found["plan_id"], found["rev"], sid)
        return f"Plan {found['plan_id']} is dropped; its {found['revisions']} revision(s) stay in the ledger."
