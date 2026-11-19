"""Draft: the draft pull request of a child of a plan with locked tests (docs/system.md section 13, part 5). At spawn,
the parent's harness makes the child's branch from the plan branch with one start commit (START, a note with the
issue's link: GitHub opens no pull request without a commit) and opens one draft pull request from it into the plan
branch, kept in the ticket (DRAFTS). The parent watches it (mcp__claude-code-remote__subscribe_pr_activity), so a CI
result on any push of the child wakes it. The child's registration is the first commit after the start commit;
harness ci (utils/orchestra/ci.py) skips the start commit, and a branch holding only it is waiting."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from harness.utils.git.facts import top
from harness.utils.git.github import GitHubError, repo_of
from harness.utils.git.run import git
from harness.utils.ledger.recorder import Recorder
from harness.utils.orchestra.brief import branch, subject
from harness.utils.orchestra.fetch import FetchError, put_files
from harness.utils.orchestra.issues import ISSUES
from harness.utils.orchestra.locked import LOCK, on_origin
from harness.utils.plan import tickets
from harness.utils.shapes import Card, PlanStore

DRAFTS = "drafts"  # the ticket's key: {name: {repo, number, url, node, watched?}}
START = ".harness/notes/{name}/start.md"
WATCH = "mcp__claude-code-remote__subscribe_pr_activity"


class DraftError(ValueError):
    """The draft pull request cannot be opened; the message says why."""


def open_draft(port: PlanStore, sid: str, card: Card, unit: dict[str, Any], github: Callable[..., Any]) -> dict[str, Any]:
    """The child's draft pull request into the plan branch: opened once, after the start commit, and kept.

    Args:
        port: the ledger port.
        sid: the parent's session.
        card: the child's card.
        unit: its unit's spec {repo, path, verify, base} (card.unit_spec).
        github: call(method, path, fields?) -> the JSON answer (utils/git/github.call).

    Returns:
        The draft {repo, number, url, node}.

    Raises:
        DraftError: no lock or no issue yet, no repository URL, the start commit cannot be pushed, or GitHub refuses.
    """
    ticket, name = port.ticket(sid), card["name"]
    held = (ticket.get(DRAFTS) or {}).get(name)
    if held:
        return dict(held)
    into = (ticket.get(LOCK) or {}).get("branch")
    issue = ((ticket.get(ISSUES) or {}).get("children") or {}).get(name)
    if not into or not issue:
        raise DraftError(f"{name} has no {'plan branch' if not into else 'issue'} yet: lock, then tickets, then spawn")
    plan, root = ticket["plan"], top(ticket["plan"]["root"]) or ""
    url = unit.get("repo") or (git(root, "config", "--get", "remote.origin.url").strip() if root else "")
    ref = branch(plan["id"], name)
    if not on_origin(unit, root, ref):
        note = (f"# Start of {name} (plan {plan['id']})\n\nIssue #{issue['number']}: {issue.get('url')}\n\nThe "
                f"orchestrator made this branch from {into} so its draft pull request could open. Your registration "
                "comes next: run('orchestra', 'take').\n")
        try:
            put_files(unit, root, into, {START.format(name=name): note}, subject(issue["number"], name, "start"),
                      target=ref)
        except FetchError as e:
            raise DraftError(f"the start commit of {name} was not pushed: {str(e)[-300:]}") from e
    try:
        made = github("POST", f"repos/{repo_of(url)}/pulls", {
            "head": ref, "base": into, "title": f"[p{plan['id']}] {name}: {card['goal']}"[:200], "draft": True,
            "body": f"The work of child {name} for issue #{issue['number']}, into {into}. A draft until the "
                    "orchestrator accepts it; harness ci runs on each push."})
    except GitHubError as e:
        raise DraftError(f"the draft pull request of {name} was not opened: {str(e)[-300:]}") from e
    entry = {"repo": repo_of(url), "number": made.get("number"), "url": made.get("html_url"), "node": made.get("node_id")}

    def keep(con: sqlite3.Connection, rec: Recorder) -> None:
        fresh = tickets.latest(con, sid)
        tickets.save(con, {**fresh, DRAFTS: {**(fresh.get(DRAFTS) or {}), name: entry}})
    port.write(keep)
    return entry


def watch_call(entry: dict[str, Any]) -> dict[str, Any]:
    """The arguments of the call that watches a draft (WATCH).

    Args:
        entry: the draft {repo, number, ...}.

    Returns:
        {owner, repo, pullNumber}.
    """
    owner, _, repo = str(entry["repo"]).partition("/")
    return {"owner": owner, "repo": repo, "pullNumber": entry["number"]}
