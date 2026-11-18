"""Card: one child of a delegated plan as the plan names it (docs/05-orchestra.md section 5.1), and the grant the
user approves with the plan (5.2). clean_cards gives each card its plain shape; card_problems names every fault at
once, so the parent fixes the plan in one round.

In the cloud each child has a clone and a branch of its own, so several children may share a unit (spec 05 allows
that only with worktrees). A card's unit is "home" (the harness's repository), "none", "agent-code" or a declared
unit."""
from __future__ import annotations

import re
from collections.abc import Collection
from typing import Any

from harness.utils.plan import tickets
from harness.utils.plan.item_checks import STANDALONE, one_line, path_problems, strings
from harness.utils.shapes import Card, ChildGrant, PlanItems, PlanStore

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
SESSION = re.compile(r"^[A-Za-z0-9 ._-]{1,60}$")
HOME = "home"
MAX_GOAL, MAX_AC, MAX_ACS, MAX_PATHS = 200, 120, 6, 8
PATHS = ("read", "change", "tests")
ACTIONS = ("push",)
FILLER = frozenset(
    "it is are the a an all works work working done ok okay good fine correct correctly properly pass passes passed "
    "passing test tests goal goals holds hold as expected complete completed implemented met satisfied finished "
    "success successful successfully green and be to should must was now".split())
WORD = re.compile("[A-Za-z0-9\u00c0-\u1ef9]+")
NO_CASE = ("names no real case: say what the user or a test sees (an input and its result)")


def content_words(text: str) -> list[str]:
    """The words of text that are not filler (FILLER, compared in lower case).

    Args:
        text: one acceptance criterion.

    Returns:
        Its content words, in order.
    """
    return [w for w in WORD.findall(text) if w.lower() not in FILLER]


def clean_card(raw: Any) -> Any:
    """One card in its plain shape: name, unit and goal on one line (a | of the goal becomes /), each criterion with
    ; and | turned into ", ", paths as clean strings without duplicates. A value that is not a dict is kept as given
    for card_problems to name.

    Args:
        raw: the card as the model sent it.

    Returns:
        The cleaned Card, or raw itself when it is not a dict.
    """
    if not isinstance(raw, dict):
        return raw
    out = dict(raw)
    for key in ("name", "unit", "session"):
        if isinstance(raw.get(key), str):
            out[key] = one_line(raw[key])
    if isinstance(raw.get("goal"), str):
        out["goal"] = one_line(raw["goal"]).replace("|", "/")
    if isinstance(raw.get("ac"), list):
        out["ac"] = [re.sub(r"\s*[;|]\s*", ", ", one_line(a)) if isinstance(a, str) else a for a in raw["ac"]]
    for key in PATHS + ("actions",):
        if isinstance(raw.get(key), list):
            out[key] = list(dict.fromkeys(strings(raw[key])))
    return out


def clean_cards(value: Any) -> Any:
    """Every card of a children item cleaned (clean_card); a value that is not a list is kept as given.

    Args:
        value: the children item as given.

    Returns:
        The list of cleaned cards, or value itself.
    """
    return [clean_card(c) for c in value] if isinstance(value, list) else value


def card_faults(card: Card, units: Collection[str]) -> list[str]:
    """The faults of one card whose name is good: unit, goal, criteria, paths, session and actions.

    Args:
        card: a cleaned card.
        units: the declared units.

    Returns:
        Each fault, starting with the card's name.
    """
    name, out = card["name"], []
    if card.get("unit") not in (HOME,) + STANDALONE and card.get("unit") not in units:
        out.append(f"{name}: unit {card.get('unit')!r} is neither the home nor a declared unit")
    goal = card.get("goal")
    if not isinstance(goal, str) or not goal.strip() or len(goal) > MAX_GOAL:
        out.append(f"{name}: goal is one sentence of at most {MAX_GOAL} characters")
    ac = card.get("ac")
    if not isinstance(ac, list) or not 1 <= len(ac) <= MAX_ACS:
        out.append(f"{name}: ac is 1 to {MAX_ACS} criteria")
    else:
        for n, a in enumerate(ac, 1):
            if not isinstance(a, str) or not a.strip() or len(a) > MAX_AC:
                out.append(f"{name}: AC{n} is at most {MAX_AC} characters")
            elif len(content_words(a)) < 2:
                out.append(f"{name}: AC{n} {a!r} {NO_CASE}")
    for key in PATHS:
        value = card.get(key, [])
        if not isinstance(value, list) or len(value) > MAX_PATHS or (value and path_problems(value)):
            out.append(f"{name}: {key} is at most {MAX_PATHS} paths (a folder with / or a file with an extension)")
    if "session" in card and not (isinstance(card["session"], str) and SESSION.match(card["session"])):
        out.append(f"{name}: session is a session name of at most 60 letters, digits, space, . _ or -")
    if not isinstance(card.get("actions", []), list) or set(card.get("actions", [])) - set(ACTIONS):
        out.append(f"{name}: the only action a child may take is push")
    return out


def card_problems(value: Any, units: Collection[str] = ()) -> list[str]:
    """Every fault of a children item at once: each card {name, unit, goal, ac, read?, change?, tests?, session?,
    actions?} by the rules of docs/05-orchestra.md section 5.1; names unique, a session named by one card only.

    Args:
        value: the children item, cleaned (clean_cards).
        units: the declared units.

    Returns:
        Every fault; [] when the item is good.
    """
    if not isinstance(value, list) or not value:
        return ["children is a list of cards {name, unit, goal, ac, read, change, tests, session, actions}"]
    out, names, sessions = [], set(), set()
    for card in value:
        if not isinstance(card, dict) or not isinstance(card.get("name"), str) or not NAME.match(card["name"]):
            out.append("each child has a name of a-z, 0-9 and -, starting with a letter or digit, 40 at most")
            continue
        if card["name"] in names:
            out.append(f"{card['name']}: two children have this name")
        names.add(card["name"])
        session = card.get("session")
        if isinstance(session, str) and session.lower() in sessions:
            out.append(f"{card['name']}: session {session!r} is named by another card")
        sessions.add(session.lower() if isinstance(session, str) else None)
        out += card_faults(card, units)
    return out


HOME_SPEC = {"repo": "", "path": ".", "verify": [], "base": "main"}


def unit_spec(card: Card, units: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The unit a child works in, as its card block carries it: {repo, path, verify, base}. The home (and none,
    agent-code) is the parent's own repository at its root, with the child's own verify; any other unit is the
    declared one (project.json units).

    Args:
        card: the child's card.
        units: the declared units by name, each {repo, path, verify, base}.

    Returns:
        The spec; the home's when the card's unit is not declared.
    """
    return dict(units.get(card.get("unit", HOME), HOME_SPEC))


def in_force(port: PlanStore, sid: str) -> dict[str, Any]:
    """The items of the plan in force in a session: what its units and limits come from.

    Args:
        port: the ledger port.
        sid: the session ("" for none).

    Returns:
        The approved plan's items, {} when the session has none.
    """
    return dict(tickets.approved_plan(port.ticket(sid)) or {}) if sid else {}


def plan_units(items: PlanItems | dict[str, Any], declared: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The units a plan's children may work in: the declared ones, and the plan's own repos over them (what form 1
    showed wins), each as a card block carries it {repo, path, verify, base} and its pipeline when it names one.

    Args:
        items: the plan's items (its repos item, when it has one).
        declared: the declared units by name.

    Returns:
        {name: unit}.
    """
    repos = items.get("repos") if isinstance(items, dict) and isinstance(items.get("repos"), dict) else {}
    own = {name: {"repo": spec.get("url", ""), "path": spec.get("path", "."), "verify": list(spec.get("verify") or []),
                  "base": spec.get("base", "main"), **({"pipeline": spec["pipeline"]} if spec.get("pipeline") else {})}
           for name, spec in repos.items() if isinstance(spec, dict)}
    return {**declared, **own}


def card_of(items: PlanItems, name: str) -> Card | None:
    """The card of a child by its name in a plan's children.

    Args:
        items: the plan's items.
        name: the child's name.

    Returns:
        The Card, or None when the plan names no such child.
    """
    return next((c for c in items.get("children", []) if isinstance(c, dict) and c.get("name") == name), None)


def behaviour_id(plan: int, name: str, n: int) -> str:
    """The id of the behaviour of criterion n of a child: p<plan>.<name>.ac<n> (behaviours are kept across plans, so a
    plain ac1 would collide).

    Args:
        plan: the parent plan's number.
        name: the child's name.
        n: the criterion's number, from 1.

    Returns:
        The behaviour id.
    """
    return f"p{plan}.{name}.ac{n}"


def grant(items: PlanItems) -> ChildGrant:
    """What the user approves for the children with the plan (section 5.2): the units the cards name (home left out),
    how many children, a copy of each card, and the actions each card lists.

    Args:
        items: the delegated plan's items.

    Returns:
        The ChildGrant.
    """
    cards = [dict(c) for c in items.get("children", []) if isinstance(c, dict)]
    units = list(dict.fromkeys(c["unit"] for c in cards if c.get("unit") not in (HOME,) + STANDALONE))
    return {"units": units, "count": len(cards), "cards": cards,
            "actions": {c["name"]: list(c.get("actions", [])) for c in cards}}


def with_card_files(items: PlanItems) -> PlanItems:
    """The plan's items with the change and test paths of every card added to its files and tests, so the parent's
    own gates allow every file a child will touch.

    Args:
        items: the delegated plan's items.

    Returns:
        A new dict; items itself when the plan has no children.
    """
    cards = [c for c in items.get("children", []) if isinstance(c, dict)]
    if not cards:
        return items
    files = list(dict.fromkeys(items.get("files", []) + [p for c in cards for p in c.get("change", [])]))
    tests = list(dict.fromkeys(items.get("tests", []) + [p for c in cards for p in c.get("tests", [])]))
    return {**items, "files": files, **({"tests": tests} if tests else {})}
