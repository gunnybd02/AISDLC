"""The blocks `run` reaches, with their handlers. They live in assemble because they write through its ports; mcp
only serves them.
- plan: plan_present keeps a plan and gives the form question the model asks with AskUserQuestion; plan_status."""
import re

from harness.assemble.ports import LedgerPort

PLAN_KEYS = ("title", "files", "tests")
ABSOLUTE = re.compile(r"^([A-Za-z]:|[\\/])")


def paths(value, name, required):
    if not isinstance(value, list) or not all(isinstance(p, str) and p.strip() for p in value) or (required and not value):
        raise ValueError(f"{name} is a list of paths" + (", at least one" if required else ""))
    for p in value:
        if ABSOLUTE.match(p) or ".." in re.split(r"[\\/]", p):
            raise ValueError(f"{name}: {p} is not a path inside the repository (relative, no ..)")
    return [p.replace("\\", "/") for p in value]


def checked(plan):
    if not isinstance(plan, dict) or set(plan) - set(PLAN_KEYS):
        raise ValueError(f"a plan holds only {', '.join(PLAN_KEYS)}")
    if not isinstance(plan.get("title"), str) or not plan["title"].strip():
        raise ValueError("a plan has a title")
    return {"title": plan["title"].strip(), "files": paths(plan.get("files"), "files", True),
            "tests": paths(plan.get("tests", []), "tests", False)}


def add_plan(table, port: LedgerPort):
    table.add_block("plan", "Present a plan; the user approves it in the form, and only its files may change")

    def present(plan):
        plan_id, rev, q = port.present(checked(plan))
        return (f"Plan {plan_id} rev {rev} waits for the user's approval. Ask it now with AskUserQuestion, one "
                f'question, exactly: {q} Options: "Duyệt", "Sửa plan". Never fill in the answer.')

    def status():
        waiting = port.waiting()
        if not waiting:
            return "No plan waits for an approval."
        return "\n".join(f"{w['plan_id']} rev {w['rev']} waits: {w['items']['title']}" for w in waiting)

    table.add("plan", "plan_present", "Keep a plan {title, files, tests} and give the form question", {"plan": "object"},
              present)
    table.add("plan", "plan_status", "The plans that wait for an approval", {}, status)
