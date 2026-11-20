"""Doorbell: what the parent does when a CI result on a child's draft pull request wakes it (docs/system.md section 8;
Sessions part 5, piece 4). A child cannot message its parent (auto mode refuses it); it pushes, and its harness posts
its question or handback as a comment on its draft (utils/orchestra/talk.py). The harness reads GitHub itself, never
the wake-up's text: for each child with a draft, the head commit of its pull request, the state of the project's own
CI on it (ci_state: every check run and commit status, whatever they are named; a repository with no CI has none,
and that phase is skipped), and the comments (the child's newest question or handback names the commit it goes with:
talk.newest). It records each CI state (RESULT, once per commit and state) and each new comment (COMMENT, once: from
the child or the orchestrator when a harness posted it, else the GitHub login) and names the next step:

- a question for the head commit: answer it, whatever CI does (live run 10: a question waited for CI on its empty
  commit, which tests nothing new);
- CI running, or not readable: wait;
- CI red: send it back naming the failed checks when it has handed back, else wait while it works;
- the handback for the head commit, CI green or none: check, then accept;
- else: wait.

A GitHub event in a prompt of a parent with drafts, or in the answer of ReadNotifications that reads it, gets
one line that names the doorbell (rung)."""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

from harness.utils.contracts import Event
from harness.utils.git.github import GitHubError
from harness.utils.ledger.mask import mask
from harness.utils.ledger.store import note
from harness.utils.orchestra import crew
from harness.utils.orchestra import talk
from harness.utils.orchestra.draft import DRAFTS
from harness.utils.shapes import PlanStore

RESULT, COMMENT = "ci.result", "child.comment"  # pl_notes kinds of the parent
EVENT = re.compile(r"source=[\"']?github|external-event", re.I)
NOTIFICATIONS = "ReadNotifications"  # in the cloud a CI result is a notification the model reads with this tool
MOST = 2000  # characters of a comment the ledger keeps
RED_RUNS = ("failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale")
RED_STATUSES = ("failure", "error")
RED, RUNNING, NONE, GREEN, UNKNOWN = "red", "running", "none", "green", "unknown"


def ci_state(github: Callable[..., Any], repo: str, sha: str) -> tuple[str, list[str]]:
    """The state of the project's own CI on one commit: every check run (the latest of each) and every commit status,
    whatever they are named. The parent never writes CI; a repository without CI has none, and that phase is skipped.

    Args:
        github: call(method, path, fields?) -> the JSON answer (utils/git/github.call).
        repo: "<owner>/<name>".
        sha: the commit.

    Returns:
        (state, failed): RED when a run concluded failure, timed_out, cancelled, action_required, startup_failure or
        stale, or a status is failure or error; else RUNNING when a run is not completed or a status is pending; NONE
        when there is no run and no status; else GREEN. failed names the red ones, "name (url)". UNKNOWN with the
        reason when GitHub cannot be read (the caller waits).
    """
    base = f"repos/{repo}/commits/{sha}"
    try:
        runs = (github("GET", f"{base}/check-runs?filter=latest&per_page=100") or {}).get("check_runs") or []
        statuses = (github("GET", f"{base}/status") or {}).get("statuses") or []
    except GitHubError as e:
        return UNKNOWN, [f"GitHub cannot be read: {str(e)[-200:]}"]
    failed = [f"{r.get('name')} ({r.get('html_url') or r.get('details_url') or '?'})" for r in runs
              if r.get("status") == "completed" and r.get("conclusion") in RED_RUNS]
    failed += [f"{s.get('context')} ({s.get('target_url') or '?'})" for s in statuses
               if s.get("state") in RED_STATUSES]
    if failed:
        return RED, failed
    if any(r.get("status") != "completed" for r in runs) or any(s.get("state") == "pending" for s in statuses):
        return RUNNING, []
    if not runs and not statuses:
        return NONE, []
    return GREEN, []


def ring(port: PlanStore, sid: str, github: Callable[..., Any]) -> str:
    """Read the drafts of the parent's children on GitHub, record what is new, and name each child's next step.

    Args:
        port: the ledger port.
        sid: the parent's session.
        github: call(method, path, fields?) -> the JSON answer (utils/git/github.call).

    Returns:
        One paragraph per child with a draft, or why there is nothing to read.
    """
    ticket = port.ticket(sid) or {}
    held, team = ticket.get(DRAFTS) or {}, ticket.get("crew") or {}
    if not held:
        return "No child has a draft pull request: nothing to read (spawn opens one for each child)."
    out = []
    for name, pr in sorted(held.items()):
        entry = team.get(name) or {}
        if entry.get("state") in crew.ENDED:
            out.append(f"{name}: {entry['state']}; nothing to do.")
            continue
        out.append(one(port, sid, name, pr, entry, github))
    return "\n".join(out)


def one(port: PlanStore, sid: str, name: str, pr: dict[str, Any], entry: dict[str, Any],
        github: Callable[..., Any]) -> str:
    """Read one child's draft, record what is new, and say its next step.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        pr: its draft {repo, number, url}.
        entry: its crew entry ({} when it has not started).
        github: the JSON call.

    Returns:
        The child's paragraph.
    """
    number = pr["number"]
    try:
        head = str(((github("GET", f"repos/{pr['repo']}/pulls/{number}") or {}).get("head") or {}).get("sha") or "")
        comments = talk.comments_of(github, pr)
    except GitHubError as e:
        return f"{name}: its draft #{number} cannot be read on GitHub ({str(e)[-200:]}); try the doorbell again."
    state, failed = ci_state(github, pr["repo"], head)
    keep(port, sid, RESULT, f"{pr['repo']}#{number}", f"{head}:{state}",
         {"child": name, "sha": head, "state": state, "failed": failed})
    said = heard(port, sid, name, entry, comments)
    last = talk.newest(comments, name, ("question", "handback"))  # what the child said with its head commit
    kind = (last or {}).get("kind") if (last or {}).get("sha") == head else ""
    receipt, asked = kind == "handback", kind == "question"
    short, ci = head[:12], "no CI" if state == NONE else "CI is green"
    if asked:  # a question needs no CI: its commit is empty
        step = f"it asked a question (its comment below): run('orchestra', 'answer', {{name: '{name}', text}})."
    elif state == UNKNOWN:
        step = f"the CI of {short} cannot be read ({'; '.join(failed)}): wait, then ring again."
    elif state == RUNNING:
        step = f"CI runs on {short}: wait."
    elif state == RED and receipt:
        step = (f"CI is RED on {short}: {'; '.join(failed)}. Send it back: run('orchestra', 'reject', {{name: "
                f"'{name}', why: '<these failures>'}}).")
    elif state == RED:
        step = f"CI is red on {short} while it works (no handback yet): wait."
    elif receipt:
        step = f"it handed back and {ci} on {short}: run('orchestra', 'check', {{name: '{name}'}}), then accept."
    else:
        step = f"{ci} on {short}, no handback yet: wait." + (f" {later()}" if state == NONE else "")
    return "\n".join([f"{name} (draft #{number}): {step}"] + [f"  New comment: {c}" for c in said])


LATER = 3  # minutes: with no CI no GitHub event wakes the parent (live run 9), so it looks again this soon


def later(minutes: int = LATER) -> str:
    """The short check-in a parent sets when no CI can wake it: a send_later call that runs the doorbell again.

    Args:
        minutes: how soon.

    Returns:
        The sentence with the call.
    """
    call = {"delay_minutes": minutes, "message": "Orchestra: run('orchestra', 'doorbell', {}) (no CI wakes you)."}
    return f"No CI wakes you here: look again soon: mcp__claude-code-remote__send_later {json.dumps(call)}"


def no_ci(port: PlanStore, sid: str, name: str) -> bool:
    """Whether the newest CI result the doorbell recorded for this child says the repository has no CI.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.

    Returns:
        True when the last state read was none; False when another state, or none was read yet.
    """
    for row in port.rows("SELECT text FROM pl_notes WHERE kind = ? AND sid = ? ORDER BY at DESC, rowid DESC",
                         (RESULT, sid)):
        body = json.loads(row["text"] or "{}")
        if body.get("child") == name:
            return body.get("state") == NONE
    return False


def heard(port: PlanStore, sid: str, name: str, entry: dict[str, Any], comments: list[dict[str, Any]]) -> list[str]:
    """Record each comment not recorded before (COMMENT, target its id): from the child when its harness posted it,
    from the orchestrator when the parent's harness did (talk.read), else from the GitHub login.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        entry: its crew entry.
        comments: the pull request's comments as GitHub gives them.

    Returns:
        The new comments, one short line each.
    """
    out = []
    for c in comments:
        body, meta = str(c.get("body") or ""), talk.read(c) or {}
        ours = meta.get("child") == name and meta.get("from") == talk.CHILD
        mine = meta.get("child") == name and meta.get("from") == talk.PARENT  # never the child's words
        sender = name if ours else talk.PARENT if mine else f"@{(c.get('user') or {}).get('login', '?')}"
        kept = {"from": sender, "fromSession": entry.get("sid") if ours else sid if mine else None,
                "to": entry.get("sid") if mine else sid, "url": c.get("html_url"), "body": mask(body)[:MOST]}
        if keep(port, sid, COMMENT, str(c.get("id")), name, kept):
            first = " ".join(body.split("<!--")[0].split())[:300]
            out.append(f"from {sender}: {first}")
    return out


def keep(port: PlanStore, sid: str, kind: str, target: str, key: str, body: dict[str, Any]) -> bool:
    """Write one pl_notes row unless the same kind, target and key is there already.

    Args:
        port: the ledger port.
        sid: the parent's session.
        kind: RESULT or COMMENT.
        target: what it is about.
        key: what makes it new.
        body: its text, as JSON.

    Returns:
        True when the row is new.
    """
    if port.rows("SELECT 1 AS x FROM pl_notes WHERE kind = ? AND target = ? AND key = ? LIMIT 1", (kind, target, key)):
        return False
    port.write(lambda con, rec: note(con, kind, target, key, json.dumps(body, ensure_ascii=False), sid,
                                     int(time.time() * 1000)))
    return True


def rung(port: PlanStore, event: Event) -> list[str]:
    """At a prompt of a parent whose children have drafts, or at the answer of NOTIFICATIONS (live run 2: in the
    cloud a CI result wakes the parent as a notification, not as a prompt): when it holds a GitHub event, the line that
    names the doorbell.

    Args:
        port: the ledger port.
        event: the UserPromptSubmit hook call, or the PostToolUse call of any tool.

    Returns:
        The line, or [].
    """
    if not event.session:
        return []
    if event.kind == "UserPromptSubmit":
        said = str((event.input or {}).get("prompt") or "")
    elif event.kind == "PostToolUse" and event.tool == NOTIFICATIONS:
        said = "\n".join(words(event.response))
    else:
        return []
    if not EVENT.search(said):
        return []
    if not (port.ticket(event.session) or {}).get(DRAFTS):
        return []
    return ["A GitHub event woke you: run('orchestra', 'doorbell', {}). The harness reads each child's CI result and "
            "new comments on GitHub itself, records them, and names the next step."]


def words(value: Any) -> list[str]:
    """Every text in a tool's answer, however it is nested (a JSON answer would hide quotes behind backslashes).

    Args:
        value: the answer: text, a list or an object.

    Returns:
        The texts, in order.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [w for v in value.values() for w in words(v)]
    if isinstance(value, (list, tuple)):
        return [w for v in value for w in words(v)]
    return []
