"""The plan as the user reads it: the ## Plan block (overview and code first when the plan has code), and the form
question that approves one revision of it. The block's sha is the revision's sha (pl_plan_revs)."""
import hashlib

from harness.utils.contracts import YES

REFINE_LABEL = "Sửa plan"
HEADER = f"{YES} plan"


def question(items, plan_id, rev):
    return f'{YES} plan "{items.get("title", "")}" ({plan_id} rev {rev})?'


def form_call(items, plan_id, rev):
    """What the model asks, exactly: one question, two options, never an answer of its own."""
    return (f"Ask it now with AskUserQuestion, one question, exactly: {question(items, plan_id, rev)} Header: "
            f"\"{HEADER}\". Options: \"{YES}\", \"{REFINE_LABEL}\". Never fill in the answer.")


def bullets(title, values):
    return [f"**{title}**"] + [f"- {v}" for v in values] if values else []


def block(items, plan_id, rev):
    """The ## Plan block of a revision, in the order of docs 04 (render.py)."""
    out = [f"## Plan: {items.get('title', '')} ({plan_id} rev {rev})"]
    if items.get("code"):
        ov = items.get("overview") or {}
        for key in ("problem", "need", "how", "accept"):
            out += bullets(key.capitalize(), ov.get(key, []) if isinstance(ov.get(key), list) else [ov.get(key)])
        for c in items["code"]:
            out += [f"**Code** `{c['file']}`: {c['reason']}", "```", c["code"], "```"]
    out += bullets("Services", items.get("services", []))
    if items.get("branch"):
        out.append(f"**Branch** {items['branch']}")
    if items.get("root"):
        out.append(f"**Root** {items['root']}")
    for title, key in (("What", "what"), ("Files", "files"), ("Tests", "tests"), ("Checks", "checks")):
        out += bullets(title, items.get(key, []))
    if items.get("steps"):
        out.append("**Commit**")
        out += [f"{n}. {s['commit']} | {', '.join(s.get('files', []))} | {', '.join(s.get('tests', []))} | "
                f"{'; '.join(s.get('points', []))}" for n, s in enumerate(items["steps"], 1)]
    elif items.get("commit"):
        out.append(f"**Commit** {items['commit']}")
    out += bullets("Behaviors", [f"{b['id']}: {b.get('what', '')}" for b in items.get("behaviors", [])])
    out += bullets("Network", [f"{n['host']}:{n['port']} - {n['why']}" for n in items.get("network", [])])
    out += bullets("Commands", items.get("commands", []))
    out += bullets("Children", [f"{c['name']} ({c['unit']}): {c['goal']}" for c in items.get("children", [])])
    for title, key in (("Team skills", "teamSkills"), ("Assumptions", "assumptions"), ("Not doing", "notDoing"),
                       ("Risks", "risks")):
        out += bullets(title, items.get(key, []))
    return "\n".join(out)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
