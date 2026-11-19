"""Talk: the words between a parent and its child, as comments on GitHub (docs/system.md section 12). A child cannot
message its parent (auto mode refuses it, probes of 2026-11-19), and nothing of the talk is committed on a branch:
each side's harness posts its words as one comment on the child's draft pull request (or its issue), its last line
MARK with a JSON meta {kind, child, plan, from, ...}; from is CHILD or PARENT. The poster's ledger keeps each comment
it posted (SAID). Secrets are masked before a comment leaves. read gives the meta of a harness comment, newest the
newest one of a child from one side; the parent's doorbell (utils/orchestra/doorbell.py) records every comment."""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable
from typing import Any, Optional

from harness.utils.git.github import GitHubError
from harness.utils.ledger.mask import mask
from harness.utils.ledger.store import note
from harness.utils.shapes import PlanStore

MARK = "<!-- harness-comment {meta} -->"  # the last line of every comment a harness posts
MARKED = MARK.split("{")[0].strip()  # "<!-- harness-comment"
META = re.compile(r"<!-- harness-comment (\{.*\}) -->\s*$")
SAID = "talk.said"  # pl_notes of the poster: target = the comment's URL, key = its kind, text = {id, sha256, from}
CHILD, PARENT = "child", "orchestrator"  # the two sides of the talk (from)
MOST = 60000  # characters of a comment's words: GitHub keeps 65536 at most


def body_of(kind: str, meta: dict[str, Any], lines: list[str]) -> str:
    """The text of one harness comment: a bold head line, the words (secrets masked, cut to MOST), then MARK.

    Args:
        kind: what the comment is (question, handback, sendback, answer, register).
        meta: {child, plan, from, ...}; kind is added.
        lines: the words, one paragraph each.

    Returns:
        The comment's body.
    """
    who = meta.get("child") if meta.get("from", CHILD) == CHILD else "the orchestrator"
    head = f"**{kind.capitalize()} of {who}** (plan {meta.get('plan')})"
    words = mask("\n\n".join(str(line) for line in lines))[:MOST]
    return "\n\n".join([head, words, MARK.format(meta=json.dumps({**meta, "kind": kind}, sort_keys=True))])


def post(port: PlanStore, sid: str, github: Callable[..., Any], where: dict[str, Any], kind: str,
         meta: dict[str, Any], lines: list[str]) -> dict[str, Any]:
    """Post one harness comment on a pull request or an issue and keep it in the poster's ledger (SAID).

    Args:
        port: the ledger port.
        sid: the poster's session.
        github: call(method, path, fields?) -> the JSON answer (utils/git/github.call).
        where: {repo, number, url?}: the pull request or issue.
        kind: what the comment is.
        meta: {child, plan, from, ...} for MARK.
        lines: the words.

    Returns:
        The comment as GitHub answered it ({id, html_url, ...}).

    Raises:
        GitHubError: GitHub refuses the comment.
    """
    body = body_of(kind, meta, lines)
    made = github("POST", f"repos/{where['repo']}/issues/{where['number']}/comments", {"body": body}) or {}
    kept = json.dumps({"id": made.get("id"), "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                       "from": meta.get("from", CHILD)})
    port.write(lambda con, rec: note(con, SAID, str(made.get("html_url") or where.get("url") or ""), kind, kept, sid,
                                     int(time.time() * 1000)))
    return made


def say(port: PlanStore, sid: str, kind: str, lines: list[str], github: Callable[..., Any]) -> str:
    """Post the words of a child on its draft pull request (post, from CHILD).

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
    try:
        post(port, sid, github, pr, kind, {"child": role.get("name"), "plan": role.get("plan"), "from": CHILD}, lines)
    except GitHubError as e:
        return f"The comment was not posted on #{pr['number']} ({str(e)[-200:]}); your push carries the words anyway."
    return f"It is posted on your draft pull request #{pr['number']} as a comment, for the orchestrator."


def read(comment: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The meta of a harness comment, with the comment's id and URL; None for any other comment.

    Args:
        comment: a comment as GitHub gives it ({id, body, html_url, ...}).

    Returns:
        {kind, child, plan, from, ..., id, url}; from is CHILD when an older comment names none.
    """
    found = META.search(str(comment.get("body") or ""))
    if not found:
        return None
    try:
        meta = json.loads(found.group(1))
    except ValueError:
        return None
    if not isinstance(meta, dict):
        return None
    return {"from": CHILD, **meta, "id": comment.get("id"), "url": comment.get("html_url")}


def newest(comments: Iterable[dict[str, Any]], child: str, kinds: Iterable[str],
           side: str = CHILD) -> Optional[dict[str, Any]]:
    """The newest harness comment of a child from one side whose kind is one of kinds (comments in GitHub's order).

    Args:
        comments: the comments of the pull request or issue, oldest first.
        child: the child's name.
        kinds: the kinds that count.
        side: CHILD or PARENT.

    Returns:
        Its meta (read), or None.
    """
    wanted, found = set(kinds), None
    for c in comments:
        meta = read(c)
        if meta and meta.get("child") == child and meta.get("from") == side and meta.get("kind") in wanted:
            found = meta
    return found
