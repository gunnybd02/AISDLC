"""Issues: one GitHub issue per child of a delegated plan, opened by the harness (docs/system.md section 6), and the
ticket file that records them. An issue holds the child's card in words (goal, criteria, scope, locked tests, branch)
and a machine block: one JSON object between ISSUE_OPEN and ISSUE_CLOSE, with its sha256. The ticket's ISSUES key
keeps each issue {repo, number, url, sha}; a second call opens none again. Part 4 (the child's own check) reads the
issue and compares its block with the ticket row by these hashes. Nothing secret goes in an issue: only the card.
The ticket file, <draft>__<plan sha>.csv, has one row per child (COLUMNS); harness code writes it, the model only
uploads it by its sha256 into the store's tickets folder, and the hook records that upload (utils/ledger/store.py)."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from harness.utils.git.facts import top
from harness.utils.git.github import GitHubError, repo_of
from harness.utils.git.run import git
from harness.utils.ledger import store
from harness.utils.ledger.export import FOLDER
from harness.utils.ledger.recorder import Recorder
from harness.utils.orchestra import crew, locked
from harness.utils.orchestra.brief import branch
from harness.utils.orchestra.card import unit_spec
from harness.utils.plan import tickets
from harness.utils.shapes import ApprovedPlan, Card, PlanStore

ISSUES = "issues"  # the ticket's key: {"children": {name: {repo, number, url, sha}}, "file": {title, sha256, path}}
ISSUE_OPEN, ISSUE_CLOSE = "<!-- harness-issue", "-->"
COLUMNS = ("key", "plan sha", "child", "repo", "issue", "issue sha", "branch", "scope", "AC tests", "approved at")
CSV_MIME = "text/csv"


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


def ticket_title(draft: str, plan_sha: str) -> str:
    """The file name of a plan's ticket file in the store's tickets folder.

    Args:
        draft: the plan's desk id.
        plan_sha: the sha of its approved items.

    Returns:
        "<draft>__<12 of the sha>.csv".
    """
    return f"{draft}__{plan_sha[:12]}.csv"


def ticket_csv(plan: ApprovedPlan, held: dict[str, Any], approved_at: str) -> str:
    """The ticket file: a header and one row per child, in the plan's order.

    Args:
        plan: the delegated plan in force.
        held: the issues by child name ({repo, number, sha}).
        approved_at: when the user approved the plan (ISO UTC).

    Returns:
        The CSV text.
    """
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for card in plan["children"]:
        issue = held[card["name"]]
        writer.writerow([f"{issue['number']}_issue_{card['name']}", plan.get("sha", ""), card["name"],
                         f"github.com/{issue['repo']}", f"#{issue['number']}", issue["sha"],
                         branch(plan["id"], card["name"]), ";".join(card.get("change", [])),
                         ";".join(card.get("acTests", [])), approved_at])
    return out.getvalue()


def write_ticket(port: PlanStore, sid: str, into: str) -> dict[str, str]:
    """Write the ticket file of the delegated plan in force into <into>/.harness-export/ and keep it in the ticket and
    the store's rows (the hook then knows its upload).

    Args:
        port: the ledger port.
        sid: the parent's session.
        into: a folder of the session's working folder (the Drive tool reads files only there).

    Returns:
        {title, sha256, path}.

    Raises:
        IssueError: no delegated plan, or a child without its issue.
    """
    ticket = port.ticket(sid)
    plan = crew.delegated(ticket)
    if plan is None:
        raise IssueError("no delegated plan is in force in this session")
    held = (ticket.get(ISSUES) or {}).get("children") or {}
    waiting = [c["name"] for c in plan["children"] if c["name"] not in held]
    if waiting:
        raise IssueError(f"these children have no issue yet: {', '.join(waiting)}")
    rows = port.rows("SELECT at FROM pl_plan_events WHERE plan_id = ? AND event = 'approved' ORDER BY at DESC LIMIT 1",
                     (ticket["draft"],))
    approved_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(rows[0]["at"] / 1000)) if rows else ""
    title, text = ticket_title(ticket["draft"], plan.get("sha", "")), ticket_csv(plan, held, approved_at)
    folder = Path(into) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    if not (folder / ".gitignore").exists():
        (folder / ".gitignore").write_text("*\n", encoding="utf-8")
    path = folder / title
    path.write_text(text, encoding="utf-8")
    made = {"title": title, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "path": path.resolve().as_posix()}
    store.keep_ticket(port, sid, title, made["sha256"], made["path"])
    port.write(lambda con, rec: tickets.save(con, {**tickets.latest(con, sid), ISSUES: {
        **(tickets.latest(con, sid).get(ISSUES) or {}), "file": made}}))
    return made


def upload_words(made: dict[str, str], root: str, place: str) -> str:
    """The words of the one Drive call that uploads the ticket file into the store's tickets folder.

    Args:
        made: the ticket file {title, sha256, path} (write_ticket).
        root: the store folder's id ("" when none is set).
        place: the tickets folder's id (store.place); "" when no Drive answer showed it yet.

    Returns:
        The text for the model.
    """
    if not root:
        return (f"Ticket file {made['title']} is written ({made['path']}), but no store folder is set "
                f"({store.ENV}): it stays on this machine only.")
    first = "" if place else store.find_or_make("tickets", root) + "\n"
    return (f"Ticket file {made['title']} is written.\n" + first +
            "Upload it now, once, with the Google Drive tool create_file, exactly:\n"
            f"  title: {made['title']}\n  parentId: {place or '<the id of the tickets folder Drive gave>'}\n"
            f"  contentMimeType: {CSV_MIME}\n  disableConversionToGoogleType: true\n"
            f"  base64Content: sha256:{made['sha256']}:{made['path']}\n"
            "The harness reads Drive's answer and records the upload; spawn waits for it.")


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
