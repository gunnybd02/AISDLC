"""Register: a child of a plan with locked tests checks, before any work, that its brief agrees with the records the
parent's harness wrote (docs/system.md section 7, the child's gate): its GitHub issue (the machine block and its
sha256, utils/orchestra/issues.py) and its row of the ticket file on Drive (the file's sha256 and the row's fields).

The ticket is checked by harness code at the moment Drive answers its download (ticket_seen, run by the hook): the
content whose sha256 is the brief's is read, this child's row is compared with the brief, and only the result and
the hashes are kept (pl_notes of kind child.ticket), never the file. The model only makes the Drive calls; the answer
of the download stays in its conversation, which no harness can take back. take then reads the issue itself and opens
the card plan only when both agree (register)."""
from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import json
import re
import time
from collections.abc import Callable, Iterator
from typing import Any, Optional

from harness.utils.contracts import Event
from harness.utils.git.github import GitHubError
from harness.utils.ledger.store import note
from harness.utils.orchestra.issues import COLUMNS, ISSUE_CLOSE, ISSUE_OPEN, block_sha
from harness.utils.shapes import ChildRole, PlanStore

RESULT = "child.ticket"  # pl_notes: target = the ticket file, key = ok or refused, text = {sha256, planSha, problems}
BLOCK = re.compile(re.escape(ISSUE_OPEN) + r"\s*\n(\{.*\})\s*\nsha256: ([0-9a-f]{64})\s*\n" + re.escape(ISSUE_CLOSE))


def expected(role: ChildRole) -> dict[str, Any]:
    """What the brief says a child's issue block holds.

    Args:
        role: the child's role.

    Returns:
        {plan, child, branch, start, scope, acTests}.
    """
    card = role["card"]
    return {"plan": role["draft"], "child": role["name"], "branch": role["branch"], "start": role.get("start", ""),
            "scope": list(card.get("change", [])), "acTests": list(card.get("acTests", []))}


def issue_problems(role: ChildRole, github: Callable[..., Any]) -> tuple[dict[str, Any], list[str]]:
    """Read the child's issue on GitHub and compare its machine block with its own sha256, the brief's sha and card.

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
    found = BLOCK.search(str((got or {}).get("body") or "").replace("\r\n", "\n"))
    if not found:
        return {}, [f"{name} holds no machine block"]
    try:
        block = json.loads(found.group(1))
    except ValueError:
        return {}, [f"the machine block of {name} is not JSON"]
    problems = []
    if block_sha(block) != found.group(2):
        problems.append(f"the machine block of {name} does not match its own sha256")
    if found.group(2) != issue.get("sha"):
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
