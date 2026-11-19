"""Draft: the draft pull request of a child of a plan with locked tests (docs/system.md section 13, part 5). At spawn,
the parent's harness makes the child's branch from the plan branch with one start commit (START, a note with the
issue's link: GitHub opens no pull request without a commit) and opens one draft pull request from it into the plan
branch, kept in the ticket (DRAFTS). The parent watches it (mcp__claude-code-remote__subscribe_pr_activity), so a CI
result on any push of the child wakes it: the hook records that watch from the tool's answer (watch_seen), and
started waits for it (unwatched). The child's registration is the first commit after the start commit; harness ci
(utils/orchestra/ci.py) skips the start commit, and a branch holding only it is waiting. accept turns the draft into
the pull request land merges (ready). A child cannot message its parent (auto mode refuses it, probes of 2026-11-19):
its harness posts its question and its handback as comments on the draft (say), with MARK for the parent's doorbell
(utils/orchestra/doorbell.py), and the push that goes with them runs CI, whose result wakes the parent."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Callable
from typing import Any, Optional

from harness.utils.contracts import Event, now
from harness.utils.git.facts import top
from harness.utils.git.github import GitHubError, repo_of
from harness.utils.git.run import git
from harness.utils.ledger.recorder import Recorder
from harness.utils.ledger.store import note
from harness.utils.orchestra.brief import branch, subject
from harness.utils.orchestra.fetch import FetchError, put_files
from harness.utils.orchestra.issues import ISSUES
from harness.utils.orchestra.locked import LOCK, on_origin
from harness.utils.plan import tickets
from harness.utils.shapes import Card, PlanStore, Ticket

DRAFTS = "drafts"  # the ticket's key: {name: {repo, number, url, node, watched?}}
START = ".harness/notes/{name}/start.md"
WATCH = "mcp__claude-code-remote__subscribe_pr_activity"
OTHER = re.compile(r"already\s+watch|another\s+(?:claude\s+)?(?:session|agent)", re.I)  # the events go elsewhere
READY = "mutation {{ markPullRequestReadyForReview(input: {{pullRequestId: \"{node}\"}}) {{ pullRequest {{ isDraft }} }} }}"
MARK = "<!-- harness-comment {meta} -->"  # the last line of a comment the harness of a child posts
SAID = "child.said"  # pl_notes of the child: target = the comment's URL, key = its kind, text = {id, sha256}


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
    """Turn the child's draft into a pull request ready for review (GitHub's GraphQL markPullRequestReadyForReview):
    the one pull request accept keeps and land merges.

    Args:
        ticket: the parent's ticket.
        name: the child's name.
        github: call(method, path, fields?) -> the JSON answer.

    Returns:
        {number, html_url} of the pull request; None when the child has no draft.

    Raises:
        GitHubError: GitHub refuses.
    """
    held = (ticket.get(DRAFTS) or {}).get(name)
    if not held:
        return None
    if held.get("node"):
        github("POST", "graphql", {"query": READY.format(node=held["node"])})
    return {"number": held.get("number"), "html_url": held.get("url")}


def say(port: PlanStore, sid: str, kind: str, lines: list[str], github: Callable[..., Any]) -> str:
    """Post the words of a child on its draft pull request as one comment ending with MARK, and record it.

    Args:
        port: the ledger port.
        sid: the child's session.
        kind: "question" or "handback".
        lines: the words, one paragraph each.
        github: call(method, path, fields?) -> the JSON answer.

    Returns:
        A sentence for the answer; "" for a child whose brief names no draft.
    """
    role = (port.ticket(sid) or {}).get("child") or {}
    pr = (role.get("record") or {}).get("pr") or {}
    if not pr.get("number"):
        return ""
    meta = json.dumps({"kind": kind, "child": role.get("name"), "plan": role.get("plan")}, sort_keys=True)
    body = "\n\n".join([f"**{kind.capitalize()} of {role.get('name')}** (plan {role.get('plan')})", *lines,
                        MARK.format(meta=meta)])
    try:
        made = github("POST", f"repos/{pr['repo']}/issues/{pr['number']}/comments", {"body": body})
    except GitHubError as e:
        return f"The comment was not posted on #{pr['number']} ({str(e)[-200:]}); your push carries the words anyway."
    kept = json.dumps({"id": made.get("id"), "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()})
    port.write(lambda con, rec: note(con, SAID, str(made.get("html_url") or pr.get("url")), kind, kept, sid,
                                     int(time.time() * 1000)))
    return f"It is posted on your draft pull request #{pr['number']} as a comment, for the orchestrator."


def watch_call(entry: dict[str, Any]) -> dict[str, Any]:
    """The arguments of the call that watches a draft (WATCH).

    Args:
        entry: the draft {repo, number, ...}.

    Returns:
        {owner, repo, pullNumber}.
    """
    owner, _, repo = str(entry["repo"]).partition("/")
    return {"owner": owner, "repo": repo, "pullNumber": entry["number"]}
