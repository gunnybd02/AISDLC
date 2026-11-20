"""Talk: the words between a parent and its child, as comments on GitHub (docs/system.md section 12). A child cannot
message its parent (auto mode refuses it, probes of 2026-11-19), and nothing of the talk is committed on a branch:
each side's harness posts its words as one comment on the child's draft pull request (or its issue), its last line
MARK with a JSON meta {kind, child, plan, from, ...}; from is CHILD or PARENT. The poster's ledger keeps each comment
it posted (SAID). Secrets are masked before a comment leaves. read gives the meta of a harness comment, newest the
newest one of a child from one side (with its words and its receipt, the ```json block of a handback); the parent's
doorbell (utils/orchestra/doorbell.py) records every comment. A child's question or handback goes with an empty
signal commit (signal), whose push runs CI and so wakes the parent; a failed post takes it back (unsignal)."""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable
from typing import Any, Optional

from harness.utils.contracts import asked, refused
from harness.utils.git.github import GitHubError
from harness.utils.git.run import git
from harness.utils.ledger.mask import mask
from harness.utils.ledger.store import note
from harness.utils.orchestra.brief import child_subject
from harness.utils.shapes import PlanStore

MARK = "<!-- harness-comment {meta} -->"  # the last line of every comment a harness posts
MARKED = MARK.split("{")[0].strip()  # "<!-- harness-comment"
META = re.compile(r"<!-- harness-comment (\{.*\}) -->")  # one line; the cloud may add a footer under it (run 7)
SAID = "talk.said"  # pl_notes of the poster: target = the comment's URL, key = its kind, text = {id, sha256, from}
CHILD, PARENT = "child", "orchestrator"  # the two sides of the talk (from)
MOST = 60000  # characters of a comment's words: GitHub keeps 65536 at most
BLOCK = re.compile(r"```json\n(.*?)\n```", re.S)  # a handback's receipt in its comment


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


def marker(body: str) -> Optional[re.Match[str]]:
    """The last harness marker of a comment's body, wherever it is: the cloud adds a footer under it (live run 7)."""
    found = None
    for found in META.finditer(body):
        pass
    return found


def read(comment: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The meta of a harness comment, with the comment's id and URL; None for any other comment.

    Args:
        comment: a comment as GitHub gives it ({id, body, html_url, ...}).

    Returns:
        {kind, child, plan, from, ..., id, url}; from is CHILD when an older comment names none.
    """
    found = marker(str(comment.get("body") or ""))
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
        Its meta (read) with its words and its json block (receipt, {} when none), or None.
    """
    wanted, found = set(kinds), None
    for c in comments:
        meta = read(c)
        if meta and meta.get("child") == child and meta.get("from") == side and meta.get("kind") in wanted:
            found = {**meta, "words": words_of(c), "receipt": block(c)}
    return found


def comments_of(github: Callable[..., Any], where: dict[str, Any]) -> list[dict[str, Any]]:
    """The comments of a pull request or issue, oldest first (the first 100: a child's talk is short).

    Raises:
        GitHubError: GitHub cannot be read.
    """
    return list(github("GET", f"repos/{where['repo']}/issues/{where['number']}/comments?per_page=100") or [])


def block(comment: Any) -> dict[str, Any]:
    """The ```json block of a harness comment (a handback's receipt); {} when it holds none or it does not read.

    Args:
        comment: the comment ({body, ...}) or its body.
    """
    body = str(comment.get("body") or "") if isinstance(comment, dict) else str(comment or "")
    found = BLOCK.search(body)
    try:
        value = json.loads(found.group(1)) if found else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def words_of(comment: dict[str, Any]) -> str:
    """The words of a harness comment on one line: without its head line, its json block, its MARK and anything
    under the MARK (a footer)."""
    body = str(comment.get("body") or "")
    found = marker(body)
    body = BLOCK.sub("", body[:found.start()] if found else body)
    return " ".join(" ".join(body.split("\n\n")[1:]).split())


def receipt_text(receipt: dict[str, Any]) -> str:
    """A receipt as the ```json block of a handback comment, within MOST characters: compact JSON; when too long,
    the files of each commit are left out, then the uncommitted files are cut."""
    shown = dict(receipt)
    for cut in (None, "files", "uncommitted"):
        if cut == "files":
            shown["commits"] = [{"sha": c.get("sha")} for c in shown.get("commits") or []]
        elif cut == "uncommitted":
            shown["uncommitted"] = list(shown.get("uncommitted") or [])[:20]
        text = "```json\n" + json.dumps(shown, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n```"
        if len(text) <= MOST // 2:
            break
    return text


def signal(repo: str, message: str, judge: Callable[..., Any]) -> str:
    """An empty commit the harness makes for a child's question or handback, so its push runs CI, whose result wakes
    the parent (a comment alone does not): judged first by the commit rules like any commit.

    Args:
        repo: the child's clone, on its branch.
        message: the commit message (child_subject: "#N name: ...").
        judge: judge(repo, files, message) -> the rules' verdict on a commit.

    Returns:
        The new HEAD.

    Raises:
        ValueError: the rules stop the commit (the reason).
        GitError: git refuses it.
    """
    verdict = judge(repo, [], message)
    if refused(verdict) or asked(verdict):
        raise ValueError(f"the commit is stopped: {verdict.reason}")
    git(repo, "commit", "--allow-empty", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


def tell(port: PlanStore, sid: str, github: Callable[..., Any], role: dict[str, Any], repo: str, kind: str,
         lines: list[str], judge: Callable[..., Any], n: Optional[int] = None) -> dict[str, str]:
    """A child's question or handback: the signal commit, then one comment on its draft naming that commit (meta sha,
    and n for a question). A comment that is not posted takes the commit back, so a failed post leaves none.

    Args:
        port, sid, github: the ledger port, the child's session and the GitHub call.
        role: the child's role (its record names its draft).
        repo: its clone, on its branch.
        kind: "question" or "handback".
        lines: the words.
        judge: the rules' verdict on a commit.
        n: the question's number.

    Returns:
        {sha: the signal commit, url: the comment's URL}.

    Raises:
        ValueError: no draft in the brief, the rules stop the commit, or the comment was not posted.
    """
    pr = (role.get("record") or {}).get("pr") or {}
    if not pr.get("number"):
        raise ValueError("your brief names no draft pull request to post on: ask the user")
    what = f"{kind.capitalize()}{f' {n}' if n else ''} of {role['name']} (plan {role['plan']})"
    sha = signal(repo, child_subject(role, what), judge)
    meta = {"child": role["name"], "plan": role["plan"], "from": CHILD, "sha": sha, **({"n": n} if n else {})}
    try:
        made = post(port, sid, github, pr, kind, meta, lines)
    except GitHubError as e:
        unsignal(repo, sha)
        raise ValueError(f"the {kind} was not posted on your draft #{pr['number']} ({str(e)[-200:]}); its commit was "
                         "taken back: try again") from e
    return {"sha": sha, "url": str(made.get("html_url") or pr.get("url") or "")}


def unsignal(repo: str, sha: str) -> None:
    """Take back the signal commit sha when its comment was not posted (a failed post leaves no commit): only when it
    is still the tip, keeping the work tree as it is."""
    if git(repo, "rev-parse", "HEAD").strip() == sha:
        git(repo, "reset", "-q", "--soft", "HEAD~1")
