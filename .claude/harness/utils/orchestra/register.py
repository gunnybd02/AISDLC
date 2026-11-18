"""Register: a child of a plan with locked tests checks, before any work, that its brief agrees with the records the
parent's harness wrote (docs/system.md section 7, the child's gate): its GitHub issue (the machine block and its
sha256, utils/orchestra/issues.py) and its row of the ticket file on Drive (the file's sha256 and the row's fields).

The ticket is checked by harness code at the moment Drive answers its download (ticket_seen, run by the hook): the
content whose sha256 is the brief's is read, this child's row is compared with the brief, and only the result and
the hashes are kept (pl_notes of kind child.ticket), never the file. The model only makes the Drive calls; the answer
of the download stays in its conversation, which no harness can take back. take then reads the issue itself and, when
both agree, keeps the registration in the ledger (pl_notes of kind child.registered) and commits it as the record
RECORD, the first commit of the child's branch (on_branch), before the card plan opens: its approval names that
commit, and harness ci (utils/orchestra/ci.py) sees on the branch that registration came before any code."""
from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Optional

from harness.utils.contracts import Event, asked, refused
from harness.utils.git.commit import commit
from harness.utils.git.facts import top
from harness.utils.git.run import git
from harness.utils.git.github import GitHubError
from harness.utils.ledger.store import note
from harness.utils.orchestra.brief import NOTES, child_subject
from harness.utils.orchestra.fetch import FetchError, put_files
from harness.utils.orchestra.issues import COLUMNS, format_problems, read_block
from harness.utils.orchestra.locked import on_origin
from harness.utils.shapes import ChildRole, CommitJudge, PlanStore

RESULT = "child.ticket"  # pl_notes: target = the ticket file, key = ok or refused, text = {sha256, planSha, problems}
RECORD, RECORD_FORMAT = ".harness/register/{name}.json", "harness-register/1"


def expected(role: ChildRole) -> dict[str, Any]:
    """What the brief says a child's issue block holds.

    Args:
        role: the child's role.

    Returns:
        {plan, child, path, branch, start, scope, tests, acTests}.
    """
    card = role["card"]
    return {"plan": role["draft"], "child": role["name"], "path": (role.get("unit") or {}).get("path") or ".",
            "branch": role["branch"], "start": role.get("start", ""), "scope": list(card.get("change", [])),
            "tests": list(card.get("tests", [])), "acTests": list(card.get("acTests", []))}


def issue_problems(role: ChildRole, github: Callable[..., Any]) -> tuple[dict[str, Any], list[str]]:
    """Read the child's issue on GitHub: it is in the issues' format (issues.format_problems), its block's sha256 is
    the brief's, and the block says what the brief says.

    Args:
        role: the child's role (its record names the issue).
        github: call(method, path, fields?) -> the JSON answer (utils/git/github.call).

    Returns:
        (the block, or {} when there is none; each disagreement in words).
    """
    issue = (role.get("record") or {}).get("issue") or {}
    name = f"issue #{issue.get('number')}"
    try:
        got = github("GET", f"repos/{issue.get('repo')}/issues/{issue.get('number')}")
    except GitHubError as e:
        return {}, [f"{name} cannot be read: {str(e)[-160:]}"]
    body = str((got or {}).get("body") or "")
    block, sha = read_block(body)
    problems = [f"{name} is not in the issue format: {p}" for p in format_problems(body)]
    if not block:
        return {}, problems
    if sha != issue.get("sha"):
        problems.append(f"the sha256 of {name} is not the one the brief names")
    for key, want in expected(role).items():
        if block.get(key) != want:
            problems.append(f"{name} says {key} {block.get(key)!r}, the brief says {want!r}")
    return block, problems


def row_problems(role: ChildRole, text: str) -> tuple[str, list[str]]:
    """Compare this child's row of the ticket file with its brief.

    Args:
        role: the child's role.
        text: the ticket file's text.

    Returns:
        (the row's plan sha, or ""; each disagreement in words).
    """
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0] != list(COLUMNS):
        return "", ["the ticket file does not have the harness's columns"]
    mine = [dict(zip(COLUMNS, r)) for r in rows[1:] if len(r) == len(COLUMNS) and r[2] == role["name"]]
    if len(mine) != 1:
        return "", [f"the ticket file holds {len(mine)} rows for {role['name']}, not one"]
    row, card, issue = mine[0], role["card"], (role.get("record") or {}).get("issue") or {}
    want = {"key": f"{issue.get('number')}_issue_{role['name']}", "issue": f"#{issue.get('number')}",
            "issue sha": issue.get("sha"), "branch": role["branch"], "scope": ";".join(card.get("change", [])),
            "AC tests": ";".join(card.get("acTests", []))}
    return row["plan sha"], [f"the ticket row says {k} {row[k]!r}, the brief says {v!r}" for k, v in want.items()
                             if row[k] != v]


def contents(answer: Any) -> Iterator[bytes]:
    """Every string a tool's answer holds, at any depth, as its UTF-8 bytes and, when it is base64, decoded.

    Args:
        answer: the tool's response (a JSON text is read).

    Yields:
        Byte strings that may be a file's content.
    """
    if isinstance(answer, str):
        try:
            parsed = json.loads(answer)
        except ValueError:
            parsed = None
        if isinstance(parsed, (dict, list)):
            yield from contents(parsed)
            return
        yield answer.encode("utf-8")
        try:
            yield base64.b64decode(answer, validate=True)
        except (binascii.Error, ValueError):
            pass
    elif isinstance(answer, dict):
        for value in answer.values():
            yield from contents(value)
    elif isinstance(answer, list):
        for value in answer:
            yield from contents(value)


def ticket_seen(port: PlanStore, event: Event) -> list[str]:
    """At a Drive tool's answer in a child session: when it holds the ticket file whose sha256 the brief names, check
    this child's row against the brief and keep only the result and hashes, never the content.

    Args:
        port: the ledger port.
        event: the PostToolUse hook call of an MCP tool.

    Returns:
        A note for the model when the ticket was checked; [] otherwise.
    """
    if event.kind != "PostToolUse" or not str(event.tool or "").startswith("mcp__") or not event.session:
        return []
    role = (port.ticket(event.session) or {}).get("child") or {}
    want = ((role.get("record") or {}).get("ticket")) or {}
    if not want.get("sha256"):
        return []
    for data in contents(event.response):
        if hashlib.sha256(data).hexdigest() != want["sha256"]:
            continue
        plan_sha, problems = row_problems(role, data.decode("utf-8", "replace"))
        result = {"sha256": want["sha256"], "planSha": plan_sha, "problems": problems}
        key = "refused" if problems else "ok"
        port.write(lambda con, rec: note(con, RESULT, str(want.get("title", "")), key, json.dumps(result),
                                         event.session, int(time.time() * 1000)))
        return [f"The harness checked the ticket {want.get('title')}: "
                + ("its row matches your brief; run('orchestra', 'take') again." if not problems else
                   "it does NOT match your brief: " + "; ".join(problems) + ". run('orchestra', 'take') again; it "
                   "records why and stops you.")]
    return []


class RegisterError(ValueError):
    """take is refused: the ticket is not checked yet, or the records disagree with the brief (the message says why)."""


REGISTERED = "child.registered"  # pl_notes: target = the child's branch, key = its issue number, text = the hashes


def refuse(role: ChildRole, repo: str, problems: list[str]) -> str:
    """Push one note on the child's branch saying why it stopped, as its first question, so the parent's check reads
    it (review.asked_at_tip).

    Args:
        role: the child's role.
        repo: the child's clone.
        problems: the disagreements.

    Returns:
        Where the note is, or why it could not be pushed.
    """
    rel = f"{NOTES}/{role['name']}/question-1.md"
    text = (f"# Question 1 from {role['name']} (plan {role['plan']})\n\nRegistration failed, so no work was done: "
            + "; ".join(problems) + "\n")
    unit = dict(role.get("unit") or {})
    start = role["branch"] if on_origin(unit, repo, role["branch"]) else role.get("start") or unit.get("base", "main")
    try:
        sha = put_files(unit, repo, start, {rel: text},
                        child_subject(role, f"Registration of {role['name']} failed (plan {role['plan']})"),
                        target=role["branch"])
    except FetchError as e:
        return f"The note could not be pushed ({str(e)[-200:]}): name it to the user."
    return f"The reason is in {rel} on {role['branch']} ({sha[:12]}), for the orchestrator."


def check(port: PlanStore, sid: str, root: str, github: Callable[..., Any]) -> str:
    """Register a child of a plan with locked tests before take opens its card plan: its ticket (checked by the hook at
    the Drive answer) and its issue (read now) agree with its brief. A child whose brief names no issue, or that
    registered before, passes.

    Args:
        port: the ledger port.
        sid: the child's session.
        root: the folder the session works in.
        github: call(method, path, fields?) -> the JSON answer (utils/git/github.call).

    Returns:
        "" when there is nothing to register; else the line that says it registered.

    Raises:
        RegisterError: the ticket is not checked yet (with the Drive calls to make), or a record disagrees (the
            reason is pushed on the child's branch first).
    """
    role = (port.ticket(sid) or {}).get("child") or {}
    record = role.get("record") or {}
    if not record.get("issue"):
        return ""
    if port.rows("SELECT 1 AS x FROM pl_notes WHERE kind = ? AND sid = ? LIMIT 1", (REGISTERED, sid)):
        return ""
    made = record.get("ticket") or {}
    result = ticket_result(port, sid, str(made.get("title", "")))
    if result is None:
        raise RegisterError(f"Register first: download your ticket file once with the Google Drive tool. 1. search_files "
                            f"with the query: title = '{made.get('title')}'. 2. download_file_content with the id Drive "
                            "gave. The harness checks the file itself at Drive's answer and keeps no copy of it. Then "
                            "run('orchestra', 'take') again.")
    block, problems = issue_problems(role, github)
    problems = list(result.get("problems") or []) + problems
    if block and result.get("planSha") != block.get("planSha"):
        problems.append(f"the ticket row and issue #{record['issue'].get('number')} name different plans")
    repo = top(root) or root
    if problems:
        where = refuse(role, repo, problems)
        raise RegisterError("Registration failed, so you may not work on this card: " + "; ".join(problems) + f". {where}"
                            " Stop now: end your turn. The orchestrator decides.")
    kept = {"issue": record["issue"].get("sha"), "ticket": made.get("sha256"), "plan": block.get("planSha")}
    port.write(lambda con, rec: note(con, REGISTERED, role["branch"], record["issue"].get("number"), json.dumps(kept),
                                     sid, int(time.time() * 1000)))
    return (f"Registered: issue #{record['issue'].get('number')} and your row of {made.get('title')} match your brief. "
            f"Every commit of yours names #{record['issue'].get('number')}.")


def on_branch(port: PlanStore, sid: str, repo: str, judge: CommitJudge) -> Optional[dict[str, Any]]:
    """Commit the child's registration as RECORD on the branch it stands on, through the commit gate: the next commit,
    so the first of its branch when take calls it. A branch that holds the same record already gets no commit.

    Args:
        port: the ledger port.
        sid: the child's session.
        repo: the child's clone, on its branch.
        judge: the rules' verdict on a commit.

    Returns:
        The record {format, plan, child, branch, repo, issue, issueSha, ticketSha256, planSha} with the sha of the
        commit that holds it; None for a child without an issue or not registered in this session.

    Raises:
        RegisterError: the rules stop the commit.
    """
    role = (port.ticket(sid) or {}).get("child") or {}
    issue = (role.get("record") or {}).get("issue") or {}
    rows = port.rows("SELECT text FROM pl_notes WHERE kind = ? AND sid = ? ORDER BY at DESC, rowid DESC LIMIT 1",
                     (REGISTERED, sid))
    if not issue or not rows:
        return None
    kept = json.loads(rows[0]["text"])
    body = {"format": RECORD_FORMAT, "plan": role["draft"], "child": role["name"], "branch": role["branch"],
            "repo": issue.get("repo"), "issue": issue.get("number"), "issueSha": kept.get("issue"),
            "ticketSha256": kept.get("ticket"), "planSha": kept.get("plan")}
    rel, text = RECORD.format(name=role["name"]), json.dumps(body, indent=1, sort_keys=True) + "\n"
    path = Path(repo) / rel
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return {**body, "sha": git(repo, "log", "-1", "--format=%H", "--", rel).strip()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    message = child_subject(role, f"register (issue {str(body['issueSha'])[:12]}, ticket "
                                  f"{str(body['ticketSha256'])[:12]})")
    verdict = judge(repo, [rel], message)
    if refused(verdict) or asked(verdict):
        path.unlink()
        raise RegisterError(f"the registration's commit is stopped: {verdict.reason}")
    return {**body, "sha": commit(repo, [rel], message)}


def ticket_result(port: PlanStore, sid: str, title: str) -> Optional[dict[str, Any]]:
    """The newest check of a child's ticket file.

    Args:
        port: the ledger port.
        sid: the child's session.
        title: the ticket file's name.

    Returns:
        {sha256, planSha, problems}; None when the ticket was not checked yet.
    """
    rows = port.rows("SELECT text FROM pl_notes WHERE kind = ? AND target = ? AND sid = ? ORDER BY at DESC, rowid "
                     "DESC LIMIT 1", (RESULT, title, sid))
    return json.loads(rows[0]["text"]) if rows else None
