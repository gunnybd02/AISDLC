"""plan: present a plan; the user approves it in the form, and only its files may change."""
from harness.utils.contracts import READ, WRITE, ActionError, McpAction, YES
from harness.utils.plan.desk import checked

ACTIONS = [("plan.plan_present", "PlanPresent"), ("plan.plan_status", "PlanStatus")]


class PlanPresent(McpAction):
    block, name, effect = "plan", "plan_present", WRITE
    summary = ("Keep a plan {title, files, tests} and give the form question; plan_id makes a new revision of a waiting "
               "plan")
    args_schema = {"type": "object", "properties": {"plan": {"type": "object"}, "plan_id": {"type": "string"}},
                   "required": ["plan"]}
    needs = ("plans",)

    def run(self, ctx, args):
        port, plan_id = ctx.ports["plans"], args.get("plan_id")
        items = checked(args["plan"])
        if plan_id is not None and plan_id not in {w["plan_id"] for w in port.waiting()}:
            raise ActionError(f"no plan {plan_id} waits for an approval: present a new plan without plan_id")
        plan_id, rev, q = port.present(items, plan_id)
        return (f"Plan {plan_id} rev {rev} waits for the user's approval. Ask it now with AskUserQuestion, one "
                f'question, exactly: {q} Options: "{YES}", "Sửa plan". Never fill in the answer.')


class PlanStatus(McpAction):
    block, name, effect = "plan", "plan_status", READ
    summary = "The plans that wait for an approval, and the ticket of this session: its phase, plan and commits"
    needs = ("plans", "session")

    def run(self, ctx, args):
        port, sid = ctx.ports["plans"], ctx.ports["session"]()
        waiting = port.waiting()
        lines = [f"{w['plan_id']} rev {w['rev']} waits: {w['items']['title']}" for w in waiting] or \
            ["No plan waits for an approval."]
        ticket = port.ticket(sid) if sid else None
        if ticket is None:
            return "\n".join(lines + ["This session has no ticket (phase prepare)."])
        plan = ticket.get("plan") or {}
        state = ticket["state"] + (f" ({ticket['closeReason']})" if ticket.get("closeReason") else "")
        lines.append(f"Ticket {ticket['id']}: {state}, phase {ticket['phase']}, plan {ticket.get('draft') or '-'} "
                     f"(no {plan.get('id', '-')}, rev {plan.get('rev', '-')}), commits {len(ticket['commits'])}")
        return "\n".join(lines)
