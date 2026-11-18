"""The plan as the user reads it (docs 04 sections 7.3, 8 and 10): the ## Plan block, one line per item (overview and code
first when the plan has code; the whole card on a child's line), the head line of a waiting revision, the changed
lines of a revision, and the form question that approves one revision. The block's sha is the revision's sha
(pl_plan_revs)."""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from harness.utils.contracts import YES
from harness.utils.orchestra.card import with_card_files
from harness.utils.plan.item_checks import one_line as one
from harness.utils.shapes import Card, PlanItems

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


def line(label: str, values: Any, sep: str = "; ") -> list[str]:
    """The one line of an item that is a list of points or paths.

    Args:
        label: the item's label in the block (Services, What...).
        values: its entries, or one text.
        sep: what joins them: "; " for points, ", " for paths and names.

    Returns:
        ["<label>: <entry><sep><entry>"], or [] when the item is empty.
    """
    values = [values] if isinstance(values, str) else list(values or [])
    return [f"{label}: {sep.join(one(v) for v in values)}"] if values else []


def repo_line(name: str, spec: dict[str, Any]) -> str:
    """One repository of a plan on one line: where the plan works, so the user approves the exact repository.

    Args:
        name: the repository's name in the plan.
        spec: {url, base?, verify?, path?, pipeline?}.

    Returns:
        "- <name>: <url> | base <base> | folder <path> | verify: <words> | pipeline <name>", each part only when given
        (base main when none is given).
    """
    parts = [f"- {name}: {spec.get('url', '')}", f"base {spec.get('base', 'main')}"]
    if spec.get("path") not in (None, "", "."):
        parts.append(f"folder {spec['path']}")
    if spec.get("verify"):
        parts.append("verify: " + " ".join(str(w) for w in spec["verify"]))
    if spec.get("pipeline"):
        parts.append(f"pipeline {spec['pipeline']}")
    return " | ".join(parts)


def card_line(card: Card) -> str:
    """One child of a delegated plan on one line: its whole card, so what the user approves is what the user reads.

    Args:
        card: the cleaned card (utils/orchestra/card.py).

    Returns:
        "- <name> (<unit>): <goal> | AC: <criterion>; ... | read: ... | change: ... | tests: ... | session: ... |
        actions: ...", each part only when the card has it.
    """
    parts = [f"- {card.get('name', '')} ({card.get('unit', '')}): {one(card.get('goal', ''))}"]
    if card.get("ac"):
        parts.append("AC: " + "; ".join(one(a) for a in card["ac"]))
    parts += [f"{key}: {', '.join(card[key])}" for key in ("read", "change", "tests") if card.get(key)]
    if card.get("session"):
        parts.append(f"session: {card['session']}")
    if card.get("actions"):
        parts.append(f"actions: {', '.join(card['actions'])}")
    return " | ".join(parts)


def overview_lines(items: PlanItems) -> list[str]:
    """The overview of a plan, one line per part.

    Args:
        items: the plan's items; its overview {problem, need, how, accept} is read.

    Returns:
        "Problem: ...", "Need: ...", "How: ...", "Accept: ..." for the parts given; [] without an overview.
    """
    ov = items.get("overview") if isinstance(items.get("overview"), dict) else {}
    out = []
    for key in ("problem", "need", "how", "accept"):
        out += line(key.capitalize(), ov.get(key))
    return out


def sections(items: PlanItems) -> list[tuple[str, list[str]]]:
    """The block of a plan by item, in the order of docs 04 section 7.3: (label, its lines). An item of points or
    paths is one line; code, steps, behaviours and children are a label line and one line per entry.

    Args:
        items: the plan's items, as desk.normalize keeps them (its root is not shown: the server sets it).

    Returns:
        The items the plan has, each with its lines; a plan with code starts with its overview and code, and its What
        is the title.
    """
    out: list[tuple[str, list[str]]] = []
    code = items.get("code") or []
    if code:
        out.append(("Overview", overview_lines(items)))
        out.append(("Code", ["Code:"] + [
            f"- {c['file']}" + (f": {one(c['code'])}" if one(c.get("code", "")) else "") + f" | why: {one(c['reason'])}"
            for c in code]))
    repos = items.get("repos") if isinstance(items.get("repos"), dict) else {}
    out.append(("Repos", ["Repos:"] + [repo_line(n, s) for n, s in repos.items()] if repos else []))
    limits = items.get("limits") if isinstance(items.get("limits"), dict) else {}
    out.append(("Limits", line("Limits", [f"{k} {v}" for k, v in limits.items()], ", ")))
    out.append(("Banned", line("Banned", items.get("banned"), ", ")))
    out.append(("Services", line("Services", items.get("services"), ", ")))
    out.append(("Branch", line("Branch", items.get("branch") or [])))
    out.append(("What", line("What", items.get("title", "") if code else items.get("what"))))
    out.append(("Files", line("Files", items.get("files"), ", ")))
    out.append(("Tests", line("Tests", items.get("tests"), ", ")))
    out.append(("Checks", line("Checks", items.get("checks"))))
    if items.get("steps"):
        out.append(("Commit", ["Commit:"] + [
            f"{n}. {s['commit']} | {', '.join(s.get('files', []))} | {', '.join(s.get('tests', []))} | "
            f"{'; '.join(s.get('points', []))}" for n, s in enumerate(items["steps"], 1)]))
    else:
        out.append(("Commit", line("Commit", items.get("commit") or [])))
    out.append(("Behaviors", ["Behaviors:"] + [
        f"- {b['id']}: {one(b.get('what', ''))}" + "".join(f" | {k}: {one(b[k])}" for k in ("how", "why") if b.get(k))
        for b in items.get("behaviors", [])] if items.get("behaviors") else []))
    out.append(("Network", line("Network", [f"{n['host']}:{n['port']} ({n['why']})" for n in items.get("network", [])])))
    out.append(("Commands", line("Commands", items.get("commands"))))
    out.append(("Children", ["Children:"] + [card_line(c) for c in items["children"]] if items.get("children") else []))
    out.append(("Team skills", line("Team skills", items.get("teamSkills"), ", ")))
    for label, key in (("Assumptions", "assumptions"), ("Not doing", "notDoing"), ("Risks", "risks")):
        out.append((label, line(label, items.get(key))))
    return [(label, lines) for label, lines in out if lines]


def block(items: PlanItems) -> str:
    """The ## Plan block of a plan (docs 04 section 7.3): what the user reads and approves; its sha is the revision's.

    Args:
        items: the plan's items, as desk.normalize keeps them.

    Returns:
        "## Plan" and the lines of every item (sections), joined by newlines. A plan with no code holds no overview
        here: the answer prints it above the block.
    """
    return "\n".join(["## Plan"] + [text for _, lines in sections(items) for text in lines])


def fenced(text: str) -> str:
    """A text in a text fence, as the answers show a block.

    Args:
        text: the block, or lines of it.

    Returns:
        The text between two fence lines.
    """
    return f"```text\n{text}\n```"


def head(items: PlanItems, plan_id: str, rev: int, changed_items: Sequence[str] = ()) -> str:
    """The head line of a revision that waits (docs 04 section 8).

    Args:
        items: the plan's items.
        plan_id: the desk id (pd-...).
        rev: the revision number.
        changed_items: the items a revision changed, named at the end; () for a new plan.

    Returns:
        The title, id, revision, the first 8 characters of the block's sha, the counts of files (the cards' too),
        steps and behaviours, who approves, and "Changed: ..." for a revision.
    """
    whole = with_card_files(items)  # a delegated plan touches its cards' files too
    paths = list(dict.fromkeys(list(whole.get("files", [])) + list(whole.get("tests", []))))
    text = (f'"{items.get("title", "")}": plan {plan_id} rev {rev} is waiting for the user\'s approval (sha '
            f"{sha(block(items))[:8]}): {len(paths)} files, {len(items.get('steps', []))} steps, "
            f"{len(items.get('behaviors', []))} behaviours. Only the user's \"{YES}\" in the approval form approves "
            f"this revision; \"{REFINE_LABEL}\" or a note means: make the change with plan_revise and ask with the form "
            "again. A chat word approves nothing.")
    return text + (f" Changed: {', '.join(changed_items)}." if changed_items else "")


def changed(old: PlanItems, new: PlanItems) -> str:
    """Only the lines of the block that a revision changed (docs 04 section 10).

    Args:
        old: the items of the revision before.
        new: the items of the new revision.

    Returns:
        The lines of each item whose lines differ from the old block, in the block's order, then "Removed: <labels>"
        for the items the new block no longer has; "" when the blocks are the same.
    """
    before, after = dict(sections(old)), sections(new)
    lines = [text for label, texts in after if before.get(label) != texts for text in texts]
    gone = [label for label in before if label not in dict(after)]
    return "\n".join(lines + ([f"Removed: {', '.join(gone)}"] if gone else []))


def sha(text: str) -> str:
    """The sha256 of a text.

    Args:
        text: the text (a rendered block).

    Returns:
        The hex sha256 of its UTF-8 bytes.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
