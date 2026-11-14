"""plan: present a plan as data; the user approves it in the form, and only its files may change (docs 04, section 2).
plan_present keeps a new desk plan, plan_revise a new revision of one with only the items that change, plan_drop
stops a waiting plan, plan_show and plan_status read one. Each needs the calling session."""
import os

from harness.utils.contracts import READ, WRITE, ActionError, McpAction
from harness.utils.plan import desk
from harness.utils.plan.render import block, form_call

ACTIONS = [("plan.plan_present", "PlanPresent"), ("plan.plan_revise", "PlanRevise"), ("plan.plan_show", "PlanShow"),
           ("plan.plan_status", "PlanStatus"), ("plan.plan_drop", "PlanDrop")]
NO_SESSION = "no session: the harness has not seen this session's prompt yet"
NOT_KEPT = "The plan was not kept: "


def session_of(ctx):
    sid = ctx.ports["session"]()
    if not sid:
        raise ActionError(NO_SESSION)
    return sid


def answer(head, items, plan_id, rev):
    return "\n\n".join([head, block(items, plan_id, rev), f"Write one line (the title and rev {rev}), then the form, "
                                                          f"nothing after it. {form_call(items, plan_id, rev)}"])


def target(ctx, sid, args):
    """The desk plan an action names, or the session's own: the newest waiting one, else its ticket's."""
    port, plan_id = ctx.ports["plans"], args.get("plan")
    if not plan_id:
        mine = [w for w in port.waiting() if w["sid"] == sid]
        plan_id = mine[-1]["plan_id"] if mine else (port.ticket(sid) or {}).get("draft")
    found = port.revision(plan_id) if plan_id else None
    if found is None:
        raise ActionError(f"no plan {plan_id}" if plan_id else "this session has no plan: present one")
    return found


class PlanPresent(McpAction):
    block, name, effect = "plan", "plan_present", WRITE
    summary = ("Present a plan as data (title, what, files, tests; a full plan: steps, behaviors, checks, "
               "assumptions, notDoing, risks...); kept waiting for the user's approval in the form")
    args_schema = {"type": "object", "properties": {"plan": {"type": "object"}}, "required": ["plan"]}
    needs = ("plans", "session")

    def run(self, ctx, args):
        sid, raw = session_of(ctx), args["plan"]
        items = desk.normalize(desk.clean(raw))
        problems = desk.unknown(raw) + desk.check(items, need_title=True)
        if problems:
            raise ActionError(NOT_KEPT + "; ".join(problems))
        items["root"] = os.getcwd().replace("\\", "/")  # the MCP server runs in the project's folder
        plan_id, rev, _ = ctx.ports["plans"].present(items, sid=sid)
        return answer(f"Plan {plan_id} rev {rev} ({desk.tier(items)}) waits for the user's approval.", items,
                      plan_id, rev)


class PlanRevise(McpAction):
    block, name, effect = "plan", "plan_revise", WRITE
    summary = "Change a presented plan with only the items that change; the new revision waits for the form again"
    args_schema = {"type": "object", "properties": {"plan": {"type": "string"}, "changes": {"type": "object"},
                                                    "why": {"type": "object"}}, "required": ["plan", "changes"]}
    needs = ("plans", "session")

    def run(self, ctx, args):
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
        problems = desk.check(items, need_title=False, keys=list(clean))
        if problems:
            raise ActionError(NOT_KEPT + "; ".join(problems))
        items["root"] = root
        if items == old["items"]:
            raise ActionError("nothing changed")
        why = {k: v for k, v in (args.get("why") or {}).items() if k in clean}
        plan_id, rev, _ = port.present(items, plan_id=args["plan"], sid=sid, why=why)
        return answer(f"Plan {plan_id} rev {rev} waits for the user's approval again.", items, plan_id, rev)


class PlanShow(McpAction):
    block, name, effect = "plan", "plan_show", READ
    summary = "Show the newest revision of a plan as the user reads it, with its form call"
    args_schema = {"type": "object", "properties": {"plan": {"type": "string"}}, "required": []}
    needs = ("plans", "session")

    def run(self, ctx, args):
        found = target(ctx, session_of(ctx), args)
        return answer(f"Plan {found['plan_id']} rev {found['rev']}: {found['event']}.", found["items"],
                      found["plan_id"], found["rev"])


class PlanStatus(McpAction):
    block, name, effect = "plan", "plan_status", READ
    summary = "A plan's revision, sha, state, revisions and feedback not answered yet; and this session's ticket"
    args_schema = {"type": "object", "properties": {"plan": {"type": "string"}}, "required": []}
    needs = ("plans", "session")

    def run(self, ctx, args):
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
    block, name, effect = "plan", "plan_drop", WRITE
    summary = "Drop the plan waiting for approval; its revisions stay in the ledger"
    args_schema = {"type": "object", "properties": {"plan": {"type": "string"}}, "required": []}
    needs = ("plans", "session")

    def run(self, ctx, args):
        sid = session_of(ctx)
        found = target(ctx, sid, args)
        if found["event"] != "waiting":
            raise ActionError(f"plan {found['plan_id']} does not wait for an approval ({found['event']})")
        ctx.ports["plans"].drop(found["plan_id"], found["rev"], sid)
        return f"Plan {found['plan_id']} is dropped; its {found['revisions']} revision(s) stay in the ledger."
