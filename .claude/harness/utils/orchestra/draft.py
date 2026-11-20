"""Draft: the draft pull request of a child (docs/system.md section 13, part 5), the place of its talk with the
parent (comments, utils/orchestra/talk.py). At spawn, the parent's harness makes the child's branch with one empty
start commit (GitHub opens no pull request without a commit; the branch holds no file of the talk) and opens one
draft pull request from it, into the plan branch when the plan is locked, else into the unit's base; it is kept in
the ticket (DRAFTS). The parent watches it (mcp__claude-code-remote__subscribe_pr_activity), so a CI result on any
push of the child wakes it: the hook records that watch from the tool's answer (watch_seen), and started waits for
it when the plan is locked (unwatched). harness ci (utils/orchestra/ci.py) reads the issue from the start commit's
subject; a branch whose commits change no file is waiting. accept turns the draft into the pull request land merges
(ready)."""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from typing import Any, Optional

from harness.utils.contracts import Event, now
from harness.utils.git.facts import top
from harness.utils.git.github import GitHubError, repo_of
from harness.utils.git.run import git
from harness.utils.ledger.recorder import Recorder
from harness.utils.orchestra.brief import branch, subject
from harness.utils.orchestra.fetch import FetchError, put_files
from harness.utils.orchestra.issues import ISSUES
from harness.utils.orchestra.locked import LOCK, on_origin
from harness.utils.plan import tickets
from harness.utils.shapes import Card, PlanStore, Ticket

DRAFTS = "drafts"  # the ticket's key: {name: {repo, number, url, node, watched?}}
WATCH = "mcp__claude-code-remote__subscribe_pr_activity"
OTHER = re.compile(r"already\s+watch|another\s+(?:claude\s+)?(?:session|agent)", re.I)  # the events go elsewhere
READY = "mutation {{ markPullRequestReadyForReview(input: {{pullRequestId: \"{node}\"}}) {{ pullRequest {{ isDraft }} }} }}"
READY_ROUTE = "repos/{repo}/pulls/{number}/ccr/ready_for_review"  # the cloud proxy's route when it refuses GraphQL


class DraftError(ValueError):
    """The draft pull request cannot be opened; the message says why."""


def open_draft(port: PlanStore, sid: str, card: Card, unit: dict[str, Any], github: Callable[..., Any]) -> dict[str, Any]:
    """The child's draft pull request: opened once, after the empty start commit, and kept. Every child gets one: into
    the plan branch when the plan is locked, else into its unit's base.

    Args:
        port: the ledger port.
        sid: the parent's session.
        card: the child's card.
        unit: its unit's spec {repo, path, verify, base} (card.unit_spec).
        github: call(method, path, fields?) -> the JSON answer (utils/git/github.call).

    Returns:
        The draft {repo, number, url, node}.

    Raises:
        DraftError: a locked plan's child with no issue yet, no repository URL, the start commit cannot be pushed, or
            GitHub refuses.
    """
    ticket, name = port.ticket(sid), card["name"]
    held = (ticket.get(DRAFTS) or {}).get(name)
    if held:
        return dict(held)
    lock = (ticket.get(LOCK) or {}).get("branch")
    issue = ((ticket.get(ISSUES) or {}).get("children") or {}).get(name) or {}
    if lock and not issue:
        raise DraftError(f"{name} has no issue yet: lock, then tickets, then spawn")
    into = lock or unit.get("base") or "main"
    plan, root = ticket["plan"], top(ticket["plan"]["root"]) or ""
    url = unit.get("repo") or (git(root, "config", "--get", "remote.origin.url").strip() if root else "")
    ref, number = branch(plan["id"], name), issue.get("number")
    if not on_origin(unit, root, ref):
        message = (f"{subject(number, name, 'start') if number else name + ': start'}\n\nThe orchestrator made this "
                   f"branch from {into} so its draft pull request could open; it changes no file."
                   + (f" Issue #{number}: {issue.get('url')}" if number else ""))
        try:
            put_files(unit, root, into, {}, message, target=ref)  # empty: GitHub needs a commit to open the draft
        except FetchError as e:
            raise DraftError(f"the start commit of {name} was not pushed: {str(e)[-300:]}") from e
    try:
        made = github("POST", f"repos/{repo_of(url)}/pulls", {
            "head": ref, "base": into, "title": f"[p{plan['id']}] {name}: {card['goal']}"[:200], "draft": True,
            "body": f"The work of child {name}" + (f" for issue #{number}" if number else "") + f", into {into}. A "
                    "draft until the orchestrator accepts it; the talk of child and orchestrator is in its comments"
                    + ("; harness ci runs on each push." if lock else ".")})
    except GitHubError as e:
        raise DraftError(f"the draft pull request of {name} was not opened: {str(e)[-300:]}") from e
    entry = {"repo": repo_of(url), "number": made.get("number"), "url": made.get("html_url"), "node": made.get("node_id")}

    def keep(con: sqlite3.Connection, rec: Recorder) -> None:
        fresh = tickets.latest(con, sid)
        tickets.save(con, {**fresh, DRAFTS: {**(fresh.get(DRAFTS) or {}), name: entry}})
    port.write(keep)
    return entry


def watch_seen(port: PlanStore, event: Event) -> list[str]:
    """At the answer of WATCH in the parent's session: record the watch of the draft it names (watched, the time).
    An answer that says another session or agent watches the pull request records nothing: its events go there.

    Args:
        port: the ledger port.
        event: the PostToolUse hook call of an MCP tool.

    Returns:
        A note for the model when a draft of this session was named; [] otherwise.
    """
    if event.kind != "PostToolUse" or not str(event.tool or "").endswith(WATCH[WATCH.rindex("__"):]) \
            or not event.session:
        return []
    args = event.input or {}
    slug, number = f"{args.get('owner')}/{args.get('repo')}".lower(), str(args.get("pullNumber"))
    held = (port.ticket(event.session) or {}).get(DRAFTS) or {}
    name = next((n for n, d in held.items() if str(d.get("repo")).lower() == slug and str(d.get("number")) == number), "")
    if not name:
        return []
    if OTHER.search(json.dumps(event.response, ensure_ascii=False) if not isinstance(event.response, str)
                    else event.response):
        return [f"The draft pull request #{number} of {name} is watched by another session or agent: its CI results "
                "will not wake you. Stop that watch, then watch it here again."]

    def keep(con: sqlite3.Connection, rec: Recorder) -> None:
        fresh = tickets.latest(con, event.session)
        drafts = dict(fresh.get(DRAFTS) or {})
        drafts[name] = {**drafts.get(name, {}), "watched": now()}
        tickets.save(con, {**fresh, DRAFTS: drafts})
    port.write(keep)
    return [f"The harness recorded your watch of the draft pull request #{number} of {name}: started may record it."]


def unwatched(ticket: Ticket, name: str) -> str:
    """Why a child of a plan with locked tests may not be recorded as started yet: its draft is not watched.

    Args:
        ticket: the parent's ticket.
        name: the child's name.

    Returns:
        The refusal with the call to make; "" when the plan has no lock or the draft is watched.
    """
    if not (ticket.get(LOCK) or {}).get("branch"):
        return ""
    held = (ticket.get(DRAFTS) or {}).get(name)
    if not held:
        return f"{name} has no draft pull request yet: run('orchestra', 'spawn', {{name: '{name}'}}) first"
    if held.get("watched"):
        return ""
    return (f"watch the draft pull request #{held.get('number')} of {name} first, so its CI results wake you: "
            f"{WATCH} {json.dumps(watch_call(held))}; then record the child again")


def ready(ticket: Ticket, name: str, github: Callable[..., Any]) -> Optional[dict[str, Any]]:
    """Turn the child's draft into a pull request ready for review: the one pull request accept keeps and land merges.
    GitHub's GraphQL markPullRequestReadyForReview first; when it is refused, READY_ROUTE (the cloud proxy refuses
    GraphQL with 403 and names that route: live run 2).

    Args:
        ticket: the parent's ticket.
        name: the child's name.
        github: call(method, path, fields?) -> the JSON answer.

    Returns:
        {number, html_url} of the pull request; None when the child has no draft.

    Raises:
        GitHubError: GitHub refuses both (the error of the route), or GraphQL when the draft names no repo and number.
    """
    held = (ticket.get(DRAFTS) or {}).get(name)
    if not held:
        return None
    if held.get("node"):
        try:
            github("POST", "graphql", {"query": READY.format(node=held["node"])})
        except GitHubError:
            if not (held.get("repo") and held.get("number")):
                raise
            github("POST", READY_ROUTE.format(repo=held["repo"], number=held["number"]), {})
    return {"number": held.get("number"), "html_url": held.get("url")}


def watch_call(entry: dict[str, Any]) -> dict[str, Any]:
    """The arguments of the call that watches a draft (WATCH).

    Args:
        entry: the draft {repo, number, ...}.

    Returns:
        {owner, repo, pullNumber}.
    """
    owner, _, repo = str(entry["repo"]).partition("/")
    return {"owner": owner, "repo": repo, "pullNumber": entry["number"]}
