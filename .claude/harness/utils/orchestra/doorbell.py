"""Doorbell: what the parent does when a CI result on a child's draft pull request wakes it (docs/system.md section 8;
Sessions part 5, piece 4). A child cannot message its parent (auto mode refuses it); it pushes, and its harness posts
its question or handback as a comment on its draft (utils/orchestra/draft.say). The harness reads GitHub itself, never
the wake-up's text: for each child with a draft, the head commit of its pull request, the CHECK run on it, the FAIL
lines of that job's log when it failed, the new comments, and the files of the head commit. It records each CI result
(RESULT, once per commit and result) and each new comment (COMMENT, once: from the child, or the GitHub login, to the
parent) and names the next step:

- no result yet, or CI running: wait;
- a rule of harness ci failed: send the child back with those rules;
- its tests failed: send it back when it has handed back, else wait while it works;
- a question at the tip: answer it;
- the receipt at the tip and CI green: check, then accept;
- else: wait.

A GitHub event in a prompt of a parent with drafts, or in the answer of ReadNotifications that reads it, gets
one line that names the doorbell (rung)."""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any, Optional

from harness.utils.contracts import Event
from harness.utils.git import github as forge
from harness.utils.git.github import GitHubError
from harness.utils.ledger.mask import mask
from harness.utils.ledger.store import note
from harness.utils.orchestra import crew
from harness.utils.orchestra.brief import NOTES
from harness.utils.orchestra.draft import DRAFTS, MARK
from harness.utils.orchestra.work import RECEIPTS
from harness.utils.shapes import PlanStore

CHECK = "harness-ci"  # the job of the workflow (utils/orchestra/workflow.py), so the name of its check run
RESULT, COMMENT = "ci.result", "child.comment"  # pl_notes kinds of the parent
STAMP = re.compile(r"^\S+Z\s")  # the time GitHub puts before each line of a job's log
EVENT = re.compile(r"source=[\"']?github|external-event", re.I)
NOTIFICATIONS = "ReadNotifications"  # in the cloud a CI result is a notification the model reads with this tool
MOST = 2000  # characters of a comment the ledger keeps
MARKED = MARK.split("{")[0].strip()  # "<!-- harness-comment": a comment the harness of a child posted


def ring(port: PlanStore, sid: str, github: Callable[..., Any], log: Optional[Callable[..., str]] = None) -> str:
    """Read the drafts of the parent's children on GitHub, record what is new, and name each child's next step.

    Args:
        port: the ledger port.
        sid: the parent's session.
        github: call(method, path, fields?) -> the JSON answer (utils/git/github.call).
        log: text(method, path) -> a job's log as text (utils/git/github.text); None uses it.

    Returns:
        One paragraph per child with a draft, or why there is nothing to read.
    """
    ticket = port.ticket(sid) or {}
    held, team = ticket.get(DRAFTS) or {}, ticket.get("crew") or {}
    if not held:
        return "No child has a draft pull request: nothing to read (spawn opens one for a plan with locked tests)."
    out = []
    for name, pr in sorted(held.items()):
        entry = team.get(name) or {}
        if entry.get("state") in crew.ENDED:
            out.append(f"{name}: {entry['state']}; nothing to do.")
            continue
        out.append(one(port, sid, name, pr, entry, github, log or forge.text))
    return "\n".join(out)


def one(port: PlanStore, sid: str, name: str, pr: dict[str, Any], entry: dict[str, Any], github: Callable[..., Any],
        log: Callable[..., str]) -> str:
    """Read one child's draft, record what is new, and say its next step.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        pr: its draft {repo, number, url}.
        entry: its crew entry ({} when it has not started).
        github: the JSON call.
        log: the text call.

    Returns:
        The child's paragraph.
    """
    base, number = f"repos/{pr['repo']}", pr["number"]
    try:
        head = str(((github("GET", f"{base}/pulls/{number}") or {}).get("head") or {}).get("sha") or "")
        runs = (github("GET", f"{base}/commits/{head}/check-runs") or {}).get("check_runs") or []
        files = [str(f.get("filename")) for f in (github("GET", f"{base}/commits/{head}") or {}).get("files") or []]
        comments = github("GET", f"{base}/issues/{number}/comments") or []
    except GitHubError as e:
        return f"{name}: its draft #{number} cannot be read on GitHub ({str(e)[-200:]}); try the doorbell again."
    run = next((r for r in runs if r.get("name") == CHECK), {})
    status, conclusion = run.get("status") or "none", run.get("conclusion") or ""
    failures = fails(base, run, log) if conclusion and conclusion != "success" else []
    keep(port, sid, RESULT, f"{pr['repo']}#{number}", f"{head}:{conclusion or status}",
         {"child": name, "sha": head, "status": status, "conclusion": conclusion, "failures": failures,
          "url": run.get("html_url")})
    said = heard(port, sid, name, entry, comments)
    receipt = f"{RECEIPTS}/{name}.json" in files
    asked = any(f.startswith(f"{NOTES}/{name}/question-") for f in files)
    short, rules = head[:12], [f for f in failures if f.startswith("FAIL ")]
    if not run:
        step = f"no {CHECK} result on {short} yet: wait."
    elif status != "completed":
        step = f"CI runs on {short}: wait."
    elif conclusion != "success" and (rules or receipt):
        why = "; ".join(rules or failures) or f"see {run.get('html_url')}"
        step = (f"CI is RED on {short}: {why}. Send it back: run('orchestra', 'reject', {{name: '{name}', why: "
                "'<these failures>'}).")
    elif conclusion != "success":
        step = f"its tests are red on {short} while it works (no receipt yet): wait."
    elif asked:
        step = f"it asked a question (its comment below): run('orchestra', 'answer', {{name: '{name}', text}})."
    elif receipt:
        step = f"it handed back and CI is green on {short}: run('orchestra', 'check', {{name: '{name}'}}), then accept."
    else:
        step = f"CI is green on {short}, no receipt yet: wait."
    return "\n".join([f"{name} (draft #{number}): {step}"] + [f"  New comment: {c}" for c in said])


def fails(base: str, run: dict[str, Any], log: Callable[..., str]) -> list[str]:
    """The FAIL lines and the result line of a failed job's log, without GitHub's time stamps.

    Args:
        base: "repos/<owner>/<name>".
        run: the check run (its id is the Actions job's id).
        log: the text call.

    Returns:
        The lines; [] when the log cannot be read.
    """
    try:
        text = log("GET", f"{base}/actions/jobs/{run.get('id')}/logs")
    except GitHubError:
        return []
    lines = [STAMP.sub("", line).strip() for line in str(text).splitlines()]
    return [line for line in lines if line.startswith("FAIL ") or line.startswith("Result: RED")][:20]


def heard(port: PlanStore, sid: str, name: str, entry: dict[str, Any], comments: list[dict[str, Any]]) -> list[str]:
    """Record each comment not recorded before (COMMENT, target its id): from the child when its harness posted it
    (MARK names the child), else from the GitHub login; to the parent.

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
        body = str(c.get("body") or "")
        ours = MARKED in body and f'"child": "{name}"' in body
        sender = name if ours else f"@{(c.get('user') or {}).get('login', '?')}"
        kept = {"from": sender, "fromSession": entry.get("sid") if ours else None, "to": sid, "url": c.get("html_url"),
                "body": mask(body)[:MOST]}
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
