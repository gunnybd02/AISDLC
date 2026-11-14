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
    summary = "The plans that wait for an approval"
    needs = ("plans",)

    def run(self, ctx, args):
        waiting = ctx.ports["plans"].waiting()
        if not waiting:
            return "No plan waits for an approval."
        return "\n".join(f"{w['plan_id']} rev {w['rev']} waits: {w['items']['title']}" for w in waiting)
