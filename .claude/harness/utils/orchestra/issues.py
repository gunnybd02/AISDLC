"""Issues: one GitHub issue per child of a delegated plan, opened by the harness (docs/system.md section 6), and the
ticket file that records them. An issue holds the child's card in words (goal, criteria, scope, locked tests, branch)
and a machine block: one JSON object between ISSUE_OPEN and ISSUE_CLOSE, with its sha256. The ticket's ISSUES key
keeps each issue {repo, number, url, sha}; a second call opens none again. Part 4 (the child's own check) reads the
issue and compares its block with the ticket row by these hashes. Nothing secret goes in an issue: only the card."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from typing import Any

from harness.utils.git.facts import top
from harness.utils.git.github import GitHubError, repo_of
from harness.utils.git.run import git
from harness.utils.ledger.recorder import Recorder
from harness.utils.orchestra import crew, locked
from harness.utils.orchestra.brief import branch
from harness.utils.orchestra.card import unit_spec
from harness.utils.plan import tickets
from harness.utils.shapes import ApprovedPlan, Card, PlanStore

ISSUES = "issues"  # the ticket's key: {"children": {name: {repo, number, url, sha}}, "file": {...}}
ISSUE_OPEN, ISSUE_CLOSE = "<!-- harness-issue", "-->"


class IssueError(ValueError):
    """The issues cannot be opened; the message says why."""


def block_of(plan: ApprovedPlan, draft: str, card: Card, repo: str, start: str) -> dict[str, Any]:
    """The machine block of a child's issue: what part 4 checks against the ticket row.

    Args:
        plan: the delegated plan in force.
        draft: its desk id.
        card: the child's card.
        repo: the URL of the unit's repository.
        start: the plan branch the child starts from ("" for the unit's base).

    Returns:
        {plan, planSha, child, repo, branch, start, scope, acTests}.
    """
    return {"plan": draft, "planSha": plan.get("sha", ""), "child": card["name"], "repo": repo,
            "branch": branch(plan["id"], card["name"]), "start": start, "scope": list(card.get("change", [])),
            "acTests": list(card.get("acTests", []))}


def block_sha(block: dict[str, Any]) -> str:
    """The sha256 of a machine block, as its canonical JSON (keys sorted, no spaces).

    Args:
        block: the block.

    Returns:
        The hex digest.
    """
    return hashlib.sha256(json.dumps(block, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def issue_text(card: Card, block: dict[str, Any]) -> tuple[str, str, str]:
    """The title, body and block sha of a child's issue.

    Args:
        card: the child's card.
        block: its machine block (block_of).

    Returns:
        (title, body, sha).
    """
    sha = block_sha(block)
    lines = [f"Child **{card['name']}** of the delegated plan {block['plan']}, approved by the user.", "",
             f"Goal: {card['goal']}", "", "Acceptance criteria:"]
    lines += [f"- AC{n}: {a}" for n, a in enumerate(card.get("ac", []), 1)]
    lines += ["", f"Files it may change: {', '.join(block['scope']) or 'none'}",
              f"Locked acceptance tests: {', '.join(block['acTests']) or 'none'}",
              f"Branch: {block['branch']}" + (f", from {block['start']}" if block["start"] else ""), "",
              ISSUE_OPEN, json.dumps(block, sort_keys=True, ensure_ascii=False), f"sha256: {sha}", ISSUE_CLOSE]
    return f"{card['name']}: {card['goal']}"[:200], "\n".join(lines), sha


def open_issues(port: PlanStore, sid: str, units: dict[str, Any], github: Callable[..., Any]) -> list[str]:
    """Open one issue per card of the delegated plan in force on its unit's repository, and keep each in the ticket.

    Args:
        port: the ledger port.
        sid: the parent's session.
        units: the plan's units by name (card.plan_units).
        github: call(method, path, fields) -> the JSON answer (utils/git/github.call).

    Returns:
        A line per child: its issue, opened now or before.

    Raises:
        IssueError: no delegated plan, a child has started, no repository, or GitHub refuses.
    """
    ticket = port.ticket(sid)
    plan = crew.delegated(ticket)
    if plan is None:
        raise IssueError("no delegated plan is in force in this session")
    if ticket.get("crew"):
        raise IssueError("a child has started: its issue is the one it started with")
    root = top(plan["root"])
    start, lines = (ticket.get(locked.LOCK) or {}).get("branch", ""), []
    for card in plan["children"]:
        held = ((port.ticket(sid).get(ISSUES) or {}).get("children") or {}).get(card["name"])
        if held:
            lines.append(f"{card['name']}: issue #{held['number']} ({held['url']}), opened before.")
            continue
        spec = unit_spec(card, units)
        url = spec.get("repo") or (git(root, "config", "--get", "remote.origin.url").strip() if root else "")
        if not url:
            raise IssueError(f"{card['name']}: its unit has no repository URL to open an issue on")
        title, body, sha = issue_text(card, block_of(plan, ticket["draft"], card, url, start))
        try:
            made = github("POST", f"repos/{repo_of(url)}/issues", {"title": title, "body": body})
        except GitHubError as e:
            raise IssueError(f"the issue of {card['name']} was not opened: {str(e)[-200:]}") from e
        entry = {"repo": repo_of(url), "number": made.get("number"), "url": made.get("html_url"), "sha": sha}

        def keep(con: sqlite3.Connection, rec: Recorder, name: str = card["name"], kept: dict = entry) -> None:
            fresh = tickets.latest(con, sid)
            held_now = dict(fresh.get(ISSUES) or {})
            held_now["children"] = {**(held_now.get("children") or {}), name: kept}
            tickets.save(con, {**fresh, ISSUES: held_now})
        port.write(keep)
        lines.append(f"{card['name']}: issue #{entry['number']} ({entry['url']}) opened, block sha {sha[:12]}.")
    return lines
