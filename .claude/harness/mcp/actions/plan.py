"""plan: present a plan; the user approves it in the form, and only its files may change."""
from harness.mcp.actions.table import McpAction
from harness.utils.contracts import YES
from harness.utils.plan.desk import checked

BLOCK = "plan"
ABOUT = "Present a plan; the user approves it in the form, and only its files may change"


class PlanPresent(McpAction):
    name = "plan_present"
    about = ("Keep a plan {title, files, tests} and give the form question; plan_id makes a new revision of a waiting "
             "plan")
    args = {"plan": "object", "plan_id?": "string"}
    needs = ("plans",)

    def __call__(self, plan, plan_id=None):
        """A new plan, or with plan_id a new revision of a plan that waits for its approval."""
        port = self.ports["plans"]
        items = checked(plan)
        if plan_id is not None and plan_id not in {w["plan_id"] for w in port.waiting()}:
            raise ValueError(f"no plan {plan_id} waits for an approval: present a new plan without plan_id")
        plan_id, rev, q = port.present(items, plan_id)
        return (f"Plan {plan_id} rev {rev} waits for the user's approval. Ask it now with AskUserQuestion, one "
                f'question, exactly: {q} Options: "{YES}", "S\u1eeda plan". Never fill in the answer.')


class PlanStatus(McpAction):
    name = "plan_status"
    about = "The plans that wait for an approval"
    needs = ("plans",)

    def __call__(self):
        waiting = self.ports["plans"].waiting()
        if not waiting:
            return "No plan waits for an approval."
        return "\n".join(f"{w['plan_id']} rev {w['rev']} waits: {w['items']['title']}" for w in waiting)


ACTIONS = [PlanPresent, PlanStatus]
