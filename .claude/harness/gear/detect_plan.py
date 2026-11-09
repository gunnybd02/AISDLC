"""PlanGate: the findings of the approval gate.
- write.state: a write into the harness's own state (its ledger, its pause), approved plan or not;
- plan.none: a write while the session has no approved plan;
- plan.outside: a write to a file the approved plan does not name (its files and tests, under its root);
- form.prefilled: an AskUserQuestion whose answers the model filled in itself (only the user answers a form)."""
import os

from harness.utils.contracts import Detector, Finding


def key(path):
    return os.path.normcase(os.path.normpath(path))


def relative(path, root):
    """path from root, or None when path is not under root."""
    try:
        rel = os.path.relpath(key(path), key(root))
    except ValueError:  # another drive
        return None
    return None if rel == os.pardir or rel.startswith(os.pardir + os.sep) else rel


class PlanGate(Detector):
    def detect(self, event, facts):
        out = []
        if facts.get("form_prefilled"):
            out.append(Finding("form.prefilled", ", ".join(facts["form_prefilled"])))
        plan, state = facts.get("plan"), facts.get("state_dir")
        for path in facts.get("writes", []):
            if state and relative(path, state) is not None:
                out.append(Finding("write.state", path))
            elif plan is None:
                out.append(Finding("plan.none", path))
            elif relative(path, plan["root"]) not in {key(p) for p in plan["files"] + plan["tests"]}:
                out.append(Finding("plan.outside", f"{path} is not a file of plan {plan['plan_id']}"))
        return out
