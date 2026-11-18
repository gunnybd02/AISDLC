"""Locked: the plan branch of a delegated plan and the acceptance tests the parent locks on it (docs/system.md
sections 5 and 6). The parent writes each card's acTests in its own tree, at their paths from the plan's root; lock
commits them at the same paths in the unit's folder on plan/p<plan> (made from the unit's base the first time) in the
unit's repository, pushes that branch, and keeps the content hash of each file in the ticket (its lock). A child starts
from the plan branch and never changes a locked file; the parent's check runs only them. Once a child has started,
the tests are not locked again."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from harness.utils.git.facts import top
from harness.utils.git.github import GitHubError, repo_of
from harness.utils.git.run import GitError, git
from harness.utils.ledger.recorder import Recorder
from harness.utils.ledger.writes import content_hash
from harness.utils.orchestra import crew
from harness.utils.orchestra.card import unit_spec
from harness.utils.orchestra.fetch import FetchError, put_files, same_repo
from harness.utils.plan import tickets
from harness.utils.shapes import Card, PlanStore, Ticket

LOCK = "lock"  # the ticket's key: {"branch", "units": [{repo, path, base, sha, files: {path: hash}}]}


class LockError(ValueError):
    """The acceptance tests cannot be locked; the message says why."""


def plan_branch(plan: int) -> str:
    """The plan branch of a delegated plan: the children's pull requests go into it, and only the user merges it into
    the base. Outside orch/, so it never clashes with a child's branch orch/p<plan>/<name>.

    Args:
        plan: the plan's number.

    Returns:
        "plan/p<plan>".
    """
    return f"plan/p{plan}"


def in_unit(spec: dict[str, Any], path: str) -> str:
    """The path of a card's file in its unit's repository.

    Args:
        spec: the unit's spec {repo, path, ...}.
        path: the file's path, as the card names it.

    Returns:
        The path from the top of the repository.
    """
    folder = str(spec.get("path") or ".").strip("/")
    return path if folder in ("", ".") else f"{folder}/{path}"


def on_origin(spec: dict[str, Any], repo: str, ref: str) -> bool:
    """Whether a branch is on the unit's origin.

    Args:
        spec: the unit's spec.
        repo: the parent's repository root.
        ref: the branch.

    Returns:
        True when the remote has it.
    """
    remote = "origin" if same_repo(spec, repo) else spec["repo"]
    try:
        return bool(git(repo, "ls-remote", "--heads", remote, ref).strip())
    except GitError:
        return False


def lock(port: PlanStore, sid: str, units: dict[str, Any]) -> str:
    """Lock the acceptance tests of the delegated plan in force: commit them on its plan branch in each unit's
    repository, push it, and keep their hashes in the ticket.

    Args:
        port: the ledger port.
        sid: the parent's session.
        units: the plan's units by name (card.plan_units).

    Returns:
        What was locked, where.

    Raises:
        LockError: no delegated plan, no card with acTests, a child has started, a file is not written, or the push
            fails.
    """
    ticket = port.ticket(sid)
    plan = crew.delegated(ticket)
    if plan is None:
        raise LockError("no delegated plan is in force in this session")
    cards = [c for c in plan["children"] if c.get("acTests")]
    if not cards:
        raise LockError("no card names acTests: there is nothing to lock")
    if ticket.get("crew"):
        raise LockError("a child has started: its acceptance tests are locked as they were")
    root, repo = Path(plan["root"]), top(plan["root"])
    if not repo:
        raise LockError("the plan's root is in no repository")
    missing = [p for c in cards for p in c["acTests"] if not (root / p).is_file()]
    if missing:
        raise LockError(f"write these acceptance tests first (they are tests of this plan): {', '.join(missing)}")
    ref, groups = plan_branch(plan["id"]), {}
    for card in cards:
        spec = unit_spec(card, units)
        key = json.dumps({k: spec.get(k) for k in ("repo", "path", "base")}, sort_keys=True)
        groups.setdefault(key, (spec, []))[1].extend(card["acTests"])
    kept = []
    for spec, paths in groups.values():
        files = {in_unit(spec, p): (root / p).read_text(encoding="utf-8") for p in dict.fromkeys(paths)}
        start = ref if on_origin(spec, repo, ref) else spec.get("base", "main")
        try:
            sha = put_files(spec, repo, start, files, f"Acceptance tests of plan {plan['id']}, locked", target=ref)
        except FetchError as e:
            raise LockError(str(e)) from e
        kept.append({"repo": spec.get("repo") or "", "path": spec.get("path") or ".", "base": spec.get("base", "main"),
                     "sha": sha, "files": {p: content_hash(str(root / p)) for p in dict.fromkeys(paths)}})

    def write(con: sqlite3.Connection, rec: Recorder) -> None:
        fresh = tickets.latest(con, sid)
        tickets.save(con, {**fresh, LOCK: {"branch": ref, "units": kept}})
    port.write(write)
    names = ", ".join(p for unit in kept for p in unit["files"])
    return (f"Locked on {ref}: {names}. A child starts from {ref}, never changes these files, and its check runs "
            "only them. Now spawn the children.")


def plan_prs(port: PlanStore, sid: str, github: Callable[..., Any]) -> tuple[list[str], bool]:
    """The pull request of the plan branch into the base, one per locked unit: opened the first time, then read. Only
    the user merges it (the usual merge form; form 2 later).

    Args:
        port: the ledger port.
        sid: the parent's session.
        github: call(method, path, fields?) -> the JSON answer (utils/git/github.call).

    Returns:
        (a line per pull request, True when every one is merged).

    Raises:
        LockError: GitHub refuses to open or read one.
    """
    ticket = port.ticket(sid)
    plan, held = crew.delegated(ticket) or {}, dict((ticket or {}).get(LOCK) or {})
    root = top(plan.get("root") or "") if plan else None
    units, lines, done, opened = [dict(u) for u in held.get("units", [])], [], True, False
    for unit in units:
        url = unit.get("repo") or (git(root, "config", "--get", "remote.origin.url").strip() if root else "")
        slug, pr = repo_of(url), unit.get("pr") or {}
        try:
            if not pr:
                made = github("POST", f"repos/{slug}/pulls", {
                    "head": held["branch"], "base": unit["base"], "title": f"Plan {plan.get('id')}: {plan.get('title')}"[:200],
                    "body": f"The work of the children of plan {plan.get('id')}, checked against its locked acceptance "
                            f"tests ({', '.join(unit['files'])}). Merge it only with the user's word."})
                pr, opened = {"number": made.get("number"), "url": made.get("html_url")}, True
                unit["pr"] = pr
            seen = github("GET", f"repos/{slug}/pulls/{pr['number']}")
        except GitHubError as e:
            raise LockError(f"the plan pull request of {slug} cannot be opened or read: {str(e)[-200:]}") from e
        if seen.get("merged"):
            lines.append(f"The plan pull request #{pr['number']} is merged into {unit['base']}.")
        else:
            done = False
            lines.append(f"Plan pull request #{pr['number']} ({pr.get('url')}): {held['branch']} into {unit['base']}. "
                         "Ask the user to merge it (a merge form, Allow or Deny), merge it on Allow, then run('orchestra', "
                         "'land', {}) again.")
    if opened:
        port.write(lambda con, rec: tickets.save(con, {**tickets.latest(con, sid), LOCK: {**held, "units": units}}))
    return lines, done


def locked_files(ticket: Optional[Ticket]) -> dict[str, str]:
    """The files the parent locked, with their content hashes.

    Args:
        ticket: the parent's ticket.

    Returns:
        {path as the cards name it: hash}; {} when nothing is locked.
    """
    held = (ticket or {}).get(LOCK) or {}
    return {p: h for unit in held.get("units", []) for p, h in unit.get("files", {}).items()}


def changed(folder: str, ticket: Optional[Ticket], card: Card) -> list[str]:
    """The acceptance tests of a card whose content on a checkout of the child's branch is not what was locked.

    Args:
        folder: the unit's folder in the checkout.
        ticket: the parent's ticket (its lock).
        card: the child's card.

    Returns:
        Its acTests that differ from their locked hash, are gone, or were never locked.
    """
    held = locked_files(ticket)
    return [p for p in card.get("acTests", []) if not held.get(p) or content_hash(str(Path(folder) / p)) != held[p]]


def unlocked(ticket: Optional[Ticket], card: Card) -> list[str]:
    """The acceptance tests of a card that are not locked yet.

    Args:
        ticket: the parent's ticket.
        card: the child's card.

    Returns:
        Its acTests the lock does not hold.
    """
    held = locked_files(ticket)
    return [p for p in card.get("acTests", []) if p not in held]
