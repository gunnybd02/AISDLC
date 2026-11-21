"""Land: how a delegated plan's children reach their base and how the plan ends (docs/05b-orchestra-cloud.md part 3,
the user's flow of 2026-11-20). Each child merges on its own: once its check is green (the project's CI not red, the
parent's own acceptance tests green on its pull request merged with the newest base), accept merges its pull request
at the tested commit into the base, tells the child to stop and gives its archive call. There is no plan branch and
no form 2: close ends the delegated plan when every child is merged or forgotten, its ledger copy is in the store, and
the parent's own files are committed."""
from __future__ import annotations

import fnmatch
import json
from typing import Any, Callable

from harness.utils.contracts import now
from harness.utils.git.github import GitHubError
from harness.utils.ledger import store
from harness.utils.orchestra import crew, orders, synced
from harness.utils.orchestra.card import unit_spec
from harness.utils.orchestra.draft import DRAFTS, ready
from harness.utils.orchestra.review import ReviewError, child_of, set_entry
from harness.utils.shapes import Card, PlanStore, Ticket

MERGED = "merged"
ARCHIVE = "mcp__claude-code-remote__archive_session"
GONE = (crew.FORGOTTEN, crew.RELEASED, crew.REMOVED)  # children that end without a merge


def covers(card: Card, path: str) -> bool:
    """Whether a card covers a file: one of its change or test paths is it, a folder (ending in /) holding it, or a
    pattern matching it.

    Args:
        card: a child's card.
        path: a file of the plan.

    Returns:
        True when the child's work covers the file.
    """
    for p in list(card.get("change", [])) + list(card.get("tests", [])):
        if p == path or (p.endswith("/") and path.startswith(p)) or fnmatch.fnmatch(path, p):
            return True
    return False


def own_files(ticket: Ticket) -> list[str]:
    """The files of the delegated plan no card covers: the parent's own work. A card's acceptance tests are no own
    file: lock keeps them in the ledger and each child's start commit adds them to its branch (no plan branch).

    Args:
        ticket: the parent's ticket.

    Returns:
        Those files, in the plan's order.
    """
    plan, cards = ticket["plan"], ticket["plan"].get("children", [])
    return [f for f in plan.get("files", []) if not any(covers(c, f) or f in c.get("acTests", []) for c in cards)]


def accept(port: PlanStore, sid: str, name: str, units: dict[str, Any], github: Callable[..., Any]) -> str:
    """Merge a child whose check is green this round: its pull request, at the commit the check tested, into the base
    it must go to (its unit's base). The user's approval of the
    delegated plan covers this merge: it runs in harness code, so the merge gate (utils/forge/merges.py) writes no
    pass and still asks the user for any merge by the merge tool. Then the child is told to stop.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        units: the declared units by name.
        github: call(method, path, fields) -> the JSON answer (utils/git/github.call).

    Returns:
        What was merged, the stop order's call and the archive call.

    Raises:
        ReviewError: no green check this round, no pull request, a head that moved since the check, another base, or
            GitHub refuses.
    """
    ticket, card, entry = child_of(port, sid, name)
    if entry.get("checkedAt") is None or entry.get("checkedAt") != entry.get("backs", 0):
        raise ReviewError(f"{name} has not passed a check this round: run('orchestra', 'check', {{name}}) first")
    tested = str((entry.get("lastCheck") or {}).get("sha") or "")
    held = (ticket.get(DRAFTS) or {}).get(name) or entry.get("pr") or {}
    if not held.get("repo") or not held.get("number"):
        raise ReviewError(f"{name} has no pull request to merge (spawn opens one for every child)")
    into = unit_spec(card, units).get("base", "main")  # no plan branch: a child merges into its unit base
    path = f"repos/{held['repo']}/pulls/{held['number']}"
    try:
        pr = github("GET", path) or {}
        head, base = str((pr.get("head") or {}).get("sha") or ""), str((pr.get("base") or {}).get("ref") or into)
        if head != tested:
            raise ReviewError(f"the head of #{held['number']} moved since the check ({tested[:12]} -> {head[:12]}): "
                              f"run('orchestra', 'check', {{name: '{name}'}}) again")
        if base != into:
            raise ReviewError(f"#{held['number']} goes into {base}, not {into}: it is not merged")
        if pr.get("draft"):
            ready(ticket, name, github)
        done = github("PUT", f"{path}/merge", {"merge_method": "merge", "sha": tested,
                                               "commit_title": f"Merge {name} (pull request #{held['number']})"}) or {}
    except GitHubError as e:
        raise ReviewError(f"#{held['number']} of {name} was not merged ({str(e)[-200:]}): check it again, or send it "
                          "back") from e
    sha = str(done.get("sha") or "")
    set_entry(port, sid, name, card, {"state": crew.ACCEPTED, MERGED: {"sha": sha, "at": now()},
                                      "pr": {"number": held["number"], "url": held.get("url"), "repo": held["repo"],
                                             "base": into}}, crew.ACCEPTED)
    stop = orders.give(port, sid, name, "stop")
    archive = (f"Once its ledger copy is in the store (it uploads it at the stop order), archive its session: {ARCHIVE} "
               f"{json.dumps({'session_id': entry.get('sid')})}" if entry.get("sid") else "")
    return " ".join(x for x in (f"{name} accepted and merged: #{held['number']} into {into} at {tested[:12]} "
                                f"({sha[:12]}).", stop, archive) if x)


def close(port: PlanStore, sid: str, folder: str = "") -> str:
    """End the delegated plan: every child merged (accept) or forgotten, the parent's own files committed, and, with a
    store, each child's ledger copy there (utils/orchestra/synced.py) or waived by the user. No form 2 is asked.

    Args:
        port: the ledger port.
        sid: the parent's session.
        folder: the store's Drive folder; "" when none is set.

    Returns:
        The plan delivered, with the archive call of each child session; or what it still waits for.

    Raises:
        ReviewError: no delegated plan, or a child neither merged nor forgotten.
    """
    ticket = port.ticket(sid)
    plan = crew.delegated(ticket)
    if plan is None:
        raise ReviewError("no delegated plan is in force in this session")
    team = ticket.get("crew") or {}
    waiting = [c["name"] for c in plan["children"]
               if not team.get(c["name"], {}).get(MERGED) and team.get(c["name"], {}).get("state") not in GONE]
    if waiting:
        raise ReviewError(f"these children are neither merged nor forgotten: {', '.join(waiting)}; check and accept "
                          "each (accept merges it), or forget it")
    own = own_files(ticket)
    if own and ticket.get("phase") != "deliver":
        return (f"Every child is merged or forgotten. The plan waits for your own files ({', '.join(own)}): commit them "
                "with step_done, then run('orchestra', 'close', {}) again.")
    gaps = synced.missing(port, ticket) if folder else []
    if gaps:
        db = store.place(port, "db") if folder == store.folder() else ""
        return "Every child is merged or forgotten. " + synced.ask_text(ticket, folder, gaps, db)
    sessions = [e["sid"] for e in team.values() if e.get("sid") and e.get("state") != crew.REMOVED]
    lines = [f"Archive the child session {s} now, if it is not archived yet: {ARCHIVE} {json.dumps({'session_id': s})}"
             for s in sessions]
    port.close_plan(sid, port.ticket(sid), "delivered", lines)
    return "\n".join([f"Plan {plan['id']} ({ticket['draft']}) is delivered: every child is merged or forgotten."] + lines
                     + ["Delete the check-in if you set one (delete_trigger), and report to the user. GitHub deletes "
                        "each merged branch when the repository deletes head branches on merge."]
                     + ([f"Save your own ledger too: run('ledger', 'export', {{reason: 'plan-close'}}) and upload it "
                         f"(its name carries orch.{ticket['draft']}.parent; it goes to the plan's own folder of the "
                         "store, as its answer says)."] if folder else []))
