"""The plan as the user reads it: the ## Plan block (overview and code first when the plan has code), and the form
question that approves one revision of it. The block's sha is the revision's sha (pl_plan_revs)."""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from harness.utils.contracts import YES
from harness.utils.shapes import PlanItems

REFINE_LABEL = "Change plan"
HEADER = f"{YES} plan"


def question(items: PlanItems, plan_id: str, rev: int) -> str:
    """The form question that approves one revision of a plan.

    Args:
        items: the plan's items; its title is read.
        plan_id: the desk id (pd-...).
        rev: the revision number.

    Returns:
        'Approve plan "<title>" (<plan_id> rev <rev>)?'.
    """
    return f'{YES} plan "{items.get("title", "")}" ({plan_id} rev {rev})?'


def form_call(items: PlanItems, plan_id: str, rev: int) -> str:
    """What the model asks, exactly: one question, two options, never an answer of its own.

    Args:
        items: the plan's items; its title is read.
        plan_id: the desk id (pd-...).
        rev: the revision number.

    Returns:
        The text for the model: the AskUserQuestion call to make, with its question, header and options.
    """
    return (f"Ask it now with AskUserQuestion, one question, exactly: {question(items, plan_id, rev)} Header: "
            f"\"{HEADER}\". Options: \"{YES}\", \"{REFINE_LABEL}\". Never fill in the answer.")


def bullets(title: str, values: Sequence[Any]) -> list[str]:
    """The lines of one titled list of the block.

    Args:
        title: the list's title, shown in bold.
        values: its entries (each shown with str formatting).

    Returns:
        ["**<title>**", "- <value>", ...], or [] when values is empty.
    """
    return [f"**{title}**"] + [f"- {v}" for v in values] if values else []


def block(items: PlanItems, plan_id: str, rev: int) -> str:
    """The ## Plan block of a revision, in the order of docs 04 (render.py).

    Args:
        items: the plan's items, as desk.normalize keeps them.
        plan_id: the desk id (pd-...).
        rev: the revision number.

    Returns:
        The block as markdown lines joined by newlines.
    """
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


def sha(text: str) -> str:
    """The sha256 of a text.

    Args:
        text: the text (a rendered block).

    Returns:
        The hex sha256 of its UTF-8 bytes.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
