"""Issues: one GitHub issue per child of a delegated plan, opened by the harness (docs/system.md section 6), and the
ticket file that records them. An issue is in one format, FORMAT: its title "[p<plan>] <name>: <goal>", the SECTIONS
in order (the card in words, the branch and the commit format), and a machine block: one JSON object between
ISSUE_OPEN and ISSUE_CLOSE, with its sha256. The ticket's ISSUES key keeps each issue {repo, number, url, sha}; a
second call opens none again. The child's register reads an issue with read_block and format_problems.
Nothing secret goes in an issue: only the card.
Each child has its own ticket file, <draft>__<child>__<plan sha>.csv, one row (COLUMNS); harness code writes it, the
model only uploads it by its sha256 into the child's subtask folder of the store (utils/ledger/layout.py: store/
<project>/P<plan>-<title>/<child>/), and the hook records that upload (utils/ledger/store.py)."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from harness.utils.git.facts import top
from harness.utils.git.github import GitHubError, repo_of
from harness.utils.git.run import git
from harness.utils.ledger import layout, store
from harness.utils.ledger.export import FOLDER
from harness.utils.ledger.recorder import Recorder
from harness.utils.orchestra import crew, locked
from harness.utils.orchestra.brief import branch
from harness.utils.orchestra.card import unit_spec
from harness.utils.plan import tickets
from harness.utils.shapes import ApprovedPlan, Card, PlanStore

ISSUES = "issues"  # the ticket's key: {"children": {name: {repo, number, url, sha}},
#                   "files": {name: {title, sha256, path}}}
ISSUE_OPEN, ISSUE_CLOSE = "<!-- harness-issue", "-->"
BLOCK = re.compile(re.escape(ISSUE_OPEN) + r"\s*\n(\{.*\})\s*\nsha256: ([0-9a-f]{64})\s*\n" + re.escape(ISSUE_CLOSE))
FORMAT = "harness-issue/1"
SECTIONS = ("## Goal", "## Acceptance criteria", "## Scope", "## Tests", "## Locked acceptance tests", "## Branch",
            "## Commits")
COLUMNS = ("key", "plan sha", "child", "repo", "issue", "issue sha", "branch", "scope", "AC tests", "approved at")
CSV_MIME = "text/csv"


class IssueError(ValueError):
    """The issues cannot be opened; the message says why."""


def block_of(plan: ApprovedPlan, draft: str, card: Card, repo: str, start: str, path: str = ".") -> dict[str, Any]:
    """The machine block of a child's issue: what the child's register checks.

    Args:
        plan: the delegated plan in force.
        draft: its desk id.
        card: the child's card.
        repo: the URL of the unit's repository.
        start: "" (no plan branch: the child starts from its unit's base); kept in the block for its format.
        path: the unit's folder in its repository ("." for the top); the card's paths are relative to it.

    Returns:
        {format, plan, planSha, child, repo, path, branch, start, scope, tests, acTests}.
    """
    return {"format": FORMAT, "plan": draft, "planSha": plan.get("sha", ""), "child": card["name"], "repo": repo,
            "path": path or ".", "branch": branch(plan["id"], card["name"]), "start": start,
            "scope": list(card.get("change", [])), "tests": list(card.get("tests", [])),
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


def issue_text(card: Card, block: dict[str, Any], plan: int) -> tuple[str, str, str]:
    """The title, body and block sha of a child's issue, in FORMAT.

    Args:
        card: the child's card.
        block: its machine block (block_of).
        plan: the delegated plan's number.

    Returns:
        (title, body, sha).
    """
    sha, name = block_sha(block), card["name"]
    goal, criteria, scope, tests, locks, branch_, commits = SECTIONS

    def listed(paths: list[str]) -> list[str]:
        return [f"- {p}" for p in paths] or ["- none"]
    folder = "the top of the repository" if block["path"] == "." else f"the folder {block['path']} of the repository"
    lines = [f"Child **{name}** of the delegated plan {block['plan']} (plan {plan}), approved by the user.", "",
             goal, card["goal"], "", criteria, *[f"- AC{n}: {a}" for n, a in enumerate(card.get("ac", []), 1)],
             "", scope, f"Files it may change, relative to {folder}:", *listed(block["scope"]),
             "", tests, *listed(block["tests"]), "", locks, *listed(block["acTests"]),
             "", branch_, block["branch"] + (f", from {block['start']}" if block["start"] else "")
             + ". The child pushes only this branch.",
             "", commits, f"Every commit on the branch starts with this issue's number and the child's name: "
             f"`#<this issue> {name}: <what>`. The first one is the orchestrator's start, `#<this issue> {name}: "
             "start`, made from the base, which adds the locked acceptance tests (or changes no file when there are "
             "none). Before any work the child registers with a comment on this issue; the "
             "talk of child and orchestrator is in comments, never in files of the branch.",
             "", ISSUE_OPEN, json.dumps(block, sort_keys=True, ensure_ascii=False), f"sha256: {sha}", ISSUE_CLOSE]
    return f"[p{plan}] {name}: {card['goal']}"[:200], "\n".join(lines), sha


def read_block(body: str) -> tuple[dict[str, Any], str]:
    """The machine block of an issue's body and the sha256 written under it.

    Args:
        body: the issue's body.

    Returns:
        (the block, its sha as written); ({}, "") when there is no block or it is no JSON object.
    """
    found = BLOCK.search(str(body or "").replace("\r\n", "\n"))
    try:
        block = json.loads(found.group(1)) if found else None
    except ValueError:
        block = None
    return (block, found.group(2)) if isinstance(block, dict) and found else ({}, "")


def format_problems(body: str) -> list[str]:
    """Each way an issue's body is not in FORMAT: a section missing or out of order, no machine block, a block of
    another format, or a block that does not match its own sha256.

    Args:
        body: the issue's body.

    Returns:
        The problems in words; [] for a body in FORMAT.
    """
    lines, problems, last = str(body or "").replace("\r\n", "\n").split("\n"), [], -1
    for heading in SECTIONS:
        if heading not in lines:
            problems.append(f"it has no section {heading[3:]}")
        elif lines.index(heading) < last:
            problems.append(f"its section {heading[3:]} is out of order")
        else:
            last = lines.index(heading)
    block, sha = read_block(body)
    if not block:
        return problems + ["it holds no machine block"]
    if block.get("format") != FORMAT:
        problems.append(f"its machine block is of format {block.get('format')!r}, not {FORMAT}")
    if block_sha(block) != sha:
        problems.append("its machine block does not match its own sha256")
    return problems


def ticket_title(draft: str, plan_sha: str, child: str) -> str:
    """The file name of a child's ticket file in its subtask folder.

    Args:
        draft: the plan's desk id.
        plan_sha: the sha of its approved items.
        child: the child's name.

    Returns:
        "<draft>__<child>__<12 of the sha>.csv".
    """
    return f"{draft}__{child}__{plan_sha[:12]}.csv"


def ticket_csv(plan: ApprovedPlan, held: dict[str, Any], approved_at: str, only: str = "") -> str:
    """A ticket file: a header and one row per child, in the plan's order.

    Args:
        plan: the delegated plan in force.
        held: the issues by child name ({repo, number, sha}).
        approved_at: when the user approved the plan (ISO UTC).
        only: one child's name: its row alone; "" for every child.

    Returns:
        The CSV text.
    """
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for card in [c for c in plan["children"] if not only or c["name"] == only]:
        issue = held[card["name"]]
        writer.writerow([f"{issue['number']}_issue_{card['name']}", plan.get("sha", ""), card["name"],
                         f"github.com/{issue['repo']}", f"#{issue['number']}", issue["sha"],
                         branch(plan["id"], card["name"]), ";".join(card.get("change", [])),
                         ";".join(card.get("acTests", [])), approved_at])
    return out.getvalue()


def write_ticket(port: PlanStore, sid: str, into: str) -> dict[str, dict[str, str]]:
    """Write each child's ticket file of the delegated plan in force into <into>/.harness-export/ and keep them in the
    ticket and the store's rows (the hook then knows each upload).

    Args:
        port: the ledger port.
        sid: the parent's session.
        into: a folder of the session's working folder (the Drive tool reads files only there).

    Returns:
        {child name: {title, sha256, path}}, in the plan's order.

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
    folder = Path(into) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    if not (folder / ".gitignore").exists():
        (folder / ".gitignore").write_text("*\n", encoding="utf-8")
    files = {}
    for card in plan["children"]:
        title = ticket_title(ticket["draft"], plan.get("sha", ""), card["name"])
        path = folder / title
        path.write_text(ticket_csv(plan, held, approved_at, only=card["name"]), encoding="utf-8")
        made = {"title": title, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "path": path.resolve().as_posix()}
        store.keep_ticket(port, sid, title, made["sha256"], made["path"])
        files[card["name"]] = made
    port.write(lambda con, rec: tickets.save(con, {**tickets.latest(con, sid), ISSUES: {
        **(tickets.latest(con, sid).get(ISSUES) or {}), "files": files}}))
    return files


def upload_words(port: PlanStore, sid: str, plan: ApprovedPlan, files: dict[str, dict[str, str]], root: str,
                 place: str) -> str:
    """The words of the Drive calls that upload each child's ticket file into its subtask folder of the store
    (layout.run_path; first the calls that find or make the folders not known yet), or into the tickets folder for a
    plan that names no repo URL.

    Args:
        port: the ledger port.
        sid: the parent's session.
        plan: the delegated plan in force.
        files: each child's ticket file {title, sha256, path} (write_ticket).
        root: the store folder's id ("" when none is set).
        place: the tickets folder's id (store.place); "" when no Drive answer showed it yet.

    Returns:
        The text for the model.
    """
    names = ", ".join(f["title"] for f in files.values())
    if not root:
        return (f"Ticket files {names} are written, but no store folder is set ({store.ENV}): they stay on this "
                "machine only.")
    lines = [f"Ticket files are written: {names}. Upload each now, once, with the Google Drive tool create_file:"]
    for n, (name, made) in enumerate(files.items()):
        path = layout.run_path(plan, name)
        if path:
            words, parent = layout.path_words(port, sid, path, last_only=n > 0)
        else:
            words = "" if place else store.find_or_make("tickets", root)
            parent = place or "<the id of the tickets folder Drive gave>"
        lines += ([words] if words else []) + [
            f"Then create_file, exactly:\n  title: {made['title']}\n  parentId: {parent}\n"
            f"  contentMimeType: {CSV_MIME}\n  disableConversionToGoogleType: true\n"
            f"  base64Content: sha256:{made['sha256']}:{made['path']}"]
    return "\n".join(lines + ["The harness reads Drive's answers and records each upload; spawn waits for them."])


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
    if any(c.get("acTests") for c in plan["children"]) and not ticket.get(locked.LOCK):
        raise IssueError("lock the acceptance tests first (run('orchestra', 'lock', {})): an issue names its child's "
                         "locked tests")
    root = top(plan["root"])
    start, lines = "", []  # no plan branch: a child starts from its unit's base
    for card in plan["children"]:
        held = ((port.ticket(sid).get(ISSUES) or {}).get("children") or {}).get(card["name"])
        if held:
            lines.append(f"{card['name']}: issue #{held['number']} ({held['url']}), opened before.")
            continue
        spec = unit_spec(card, units)
        url = spec.get("repo") or (git(root, "config", "--get", "remote.origin.url").strip() if root else "")
        if not url:
            raise IssueError(f"{card['name']}: its unit has no repository URL to open an issue on")
        title, body, sha = issue_text(card, block_of(plan, ticket["draft"], card, url, start, spec.get("path", ".")),
                                      plan["id"])
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
