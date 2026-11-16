"""Work: what a child session does (docs/05b-orchestra-cloud.md part 2), each through the ledger port and git, never
through the model's shell.

- take: open the card plan, approved by the grant of the parent plan (no form), on the child's own branch.
- push: push the child's own branch, judged by the git rules; it pushes after every step, since its machine dies.
- ask: keep a question for the parent; the model sends it with send_message.
- handback: the child's report and what harness code reads itself (commits, verify, behaviours, uncommitted files),
  written as .harness/handback/<name>.json, committed through the commit gate and pushed with the branch."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from harness.utils.contracts import asked, refused
from harness.utils.git.commit import commit
from harness.utils.git.facts import head, top
from harness.utils.git.run import GitError, git, run_git
from harness.utils.orchestra import child
from harness.utils.plan import tickets
from harness.utils.plan.ship import audit
from harness.utils.shapes import ChildRole, CommitJudge, GitJudge, PlanStore, Ticket

if TYPE_CHECKING:
    from harness.utils.ledger.recorder import Recorder

RECEIPTS = ".harness/handback"
LISTS = ("changed", "checked", "notChecked", "risks")
PAIRS = {"testsChanged": ("test", "why"), "added": ("file", "why"), "faults": ("what", "where")}
MOST, LONGEST, LONGEST_PAIR = 10, 200, 400
NO_CHILD = ("this session is no child: only a session opened from an orchestrator's brief takes a card (its first "
            "prompt starts 'You are child session')")


class WorkError(ValueError):
    """A child's action refuses; the message says why and what to do."""


def now() -> int:
    """The time now in ms.

    Returns:
        Milliseconds since the epoch.
    """
    return int(time.time() * 1000)


def mine(port: PlanStore, sid: str) -> tuple[Ticket, ChildRole]:
    """The session's ticket and its child role.

    Args:
        port: the ledger port.
        sid: the session.

    Returns:
        (ticket, role).

    Raises:
        WorkError: the session is no child.
    """
    ticket = port.ticket(sid)
    role = child.role_of(ticket)
    if role is None:
        raise WorkError(NO_CHILD)
    return ticket, role


def switch(repo: str, name: str) -> str:
    """Stand on the branch name: the local one, else the remote one tracked, else a new one from HEAD.

    Args:
        repo: the repository's root.
        name: the branch.

    Returns:
        "on", "tracked" or "new": how the branch was reached.

    Raises:
        GitError: git refuses (uncommitted changes in the way, among others).
    """
    if git(repo, "branch", "--list", name).strip():
        git(repo, "switch", "-q", name)
        return "on"
    if git(repo, "ls-remote", "--heads", "origin", name).strip():
        git(repo, "fetch", "-q", "origin", name)
        git(repo, "switch", "-q", "-c", name, "--track", f"origin/{name}")
        return "tracked"
    git(repo, "switch", "-q", "-c", name)
    return "new"


def stopped(verdict: Any) -> bool:
    """Whether the rules stop an action: a refusal, or a question nobody in a child can answer.

    Args:
        verdict: the rules' Verdict.

    Returns:
        True when it is refused or asked.
    """
    return refused(verdict) or asked(verdict)


def take(port: PlanStore, sid: str, root: str) -> str:
    """Open the child's card plan, approved by the grant of its parent plan, on its own branch.

    Args:
        port: the ledger port.
        sid: the child's session.
        root: the folder the session works in (the repository is the one holding it).

    Returns:
        The text for the model: the plan, the branch, the behaviour ids and the loop.

    Raises:
        WorkError: no child, a card with no change paths, another plan in force, no repository, or git refuses.
    """
    ticket, role = mine(port, sid)
    held = tickets.approved_plan(ticket)
    if held:
        if held.get("branch") == role["branch"]:
            return f"Your card plan {held['plan_id']} (plan {held['id']}) is open already, on {role['branch']}."
        raise WorkError(f"plan {held['plan_id']} is in force in this session; a child works only on its card")
    if not role["card"].get("change"):
        raise WorkError("your card names no files to change: ask the orchestrator (run('orchestra', 'question'))")
    repo = top(root)
    if not repo:
        raise WorkError(f"{root} is in no git repository: stand in the clone of the plan's repository")
    try:
        how = switch(repo, role["branch"])
    except GitError as e:
        raise WorkError(f"git cannot stand on {role['branch']}: {e}") from e
    plan_id, _, _ = port.present(child.card_plan(role, repo), sid=sid)
    number = port.approve(sid, port.revision(plan_id), by=f"grant of plan {role['plan']} ({role['parent']})")
    return (f"Card plan {plan_id} (plan {number}) is open, approved by the grant of plan {role['plan']}; you are on "
            f"{role['branch']} ({how}). Files: {', '.join(role['card']['change'])}. Behaviours: "
            f"{', '.join(role['behaviours'])}. Loop: write the tests, make them pass, verify bare, "
            "run('plan', 'step_done', {message}), run('orchestra', 'push'); then run('orchestra', 'handback', {...}).")


def push(port: PlanStore, sid: str, judge: GitJudge) -> str:
    """Push the child's own branch to origin, judged like git push in a shell, and keep it in pl_git_audit.

    Args:
        port: the ledger port.
        sid: the child's session.
        judge: the rules' verdict on a git command.

    Returns:
        "Pushed <branch> (<sha>) to origin." and git's output.

    Raises:
        WorkError: no child, no card plan in force, not on its branch, a rule stops it, or git fails.
    """
    ticket, role = mine(port, sid)
    plan = tickets.approved_plan(ticket)
    repo = top(plan["root"]) if plan else None
    if not plan or not repo:
        raise WorkError("take your card first: run('orchestra', 'take')")
    on = git(repo, "branch", "--show-current").strip()
    if on != role["branch"]:
        raise WorkError(f"you are on {on or 'a detached HEAD'}; a child pushes only {role['branch']}")
    verdict = judge(repo, ["push", "-u", "origin", role["branch"]])
    if stopped(verdict):
        raise WorkError(verdict.reason)
    code, out = run_git(repo, ["push", "-u", "origin", role["branch"]])
    if code != 0:
        raise WorkError(f"git push failed (exit {code}): {out.strip()[-500:]}")
    audit(port, sid, ticket, "push", repo, role["branch"], head(repo))
    return f"Pushed {role['branch']} ({(head(repo) or '')[:12]}) to origin.\n{out.strip()[-600:]}"


def ask(port: PlanStore, sid: str, question: str) -> str:
    """Keep a question of the child for its parent, numbered; the model sends it with send_message.

    Args:
        port: the ledger port.
        sid: the child's session.
        question: one question, at most 400 characters.

    Returns:
        What to send, and to which session.

    Raises:
        WorkError: no child, or an empty or too long question.
    """
    text = " ".join(str(question).split())
    if not text or len(text) > LONGEST_PAIR:
        raise WorkError(f"a question is one to {LONGEST_PAIR} characters")
    _, role = mine(port, sid)

    def change(con: sqlite3.Connection, rec: Recorder) -> int:
        fresh = tickets.latest(con, sid)
        asks = list(fresh.get("asks", []))
        asks.append({"n": len(asks) + 1, "text": text, "at": now()})
        tickets.save(con, {**fresh, "asks": asks})
        return len(asks)
    n = port.write(change)
    return (f"Question {n} kept. Send it now with send_message to the orchestrator {role['parent']}: "
            f"\"question {n} from {role['name']} (plan {role['plan']}): {text}\". Its answer comes back as a message; "
            "go on with what you can meanwhile.")


def report_problems(report: dict[str, Any]) -> list[str]:
    """The faults of a handback report (spec 05 section 11.4): changed and checked are needed and not empty;
    notChecked, risks and testsChanged are needed (may be empty); added and faults are optional; each list holds at most
    10 entries of at most 200 characters, or two-part entries of at most 400.

    Args:
        report: the action's arguments.

    Returns:
        Every fault; [] when the report is good.
    """
    out = []
    for key in LISTS:
        value = report.get(key)
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            out.append(f"{key} is a list of points")
        elif key in ("changed", "checked") and not value:
            out.append(f"{key} names at least one point")
        elif len(value) > MOST or any(len(v) > LONGEST for v in value):
            out.append(f"{key} is at most {MOST} points of at most {LONGEST} characters")
    for key, (first, second) in PAIRS.items():
        value = report.get(key, [] if key != "testsChanged" else None)
        if not isinstance(value, list) or len(value) > MOST or not all(
                isinstance(v, dict) and isinstance(v.get(first), str) and v[first].strip()
                and len(json.dumps(v, ensure_ascii=False)) <= LONGEST_PAIR for v in value):
            out.append(f"{key} is a list of at most {MOST} entries {{{first}, {second}}} of at most {LONGEST_PAIR} "
                       "characters")
    return out


def facts(port: PlanStore, ticket: Ticket, role: ChildRole, repo: str) -> dict[str, Any]:
    """What harness code reads for a handback: the commits of the card plan and their files, the newest verify, the
    behaviours of the card's criteria (last state of each), the uncommitted files, the base commit.

    Args:
        port: the ledger port.
        ticket: the child's ticket.
        role: the child's role.
        repo: the repository's root.

    Returns:
        {commits: [{sha, files}], verify: ok/red/missing, behaviours: {id: {what, tests, status}}, uncommitted, base}.
    """
    plan = tickets.approved_plan(ticket)
    commits = []
    for sha in ticket.get("commits", []) + ticket.get("noted", []):
        try:
            files = [f for f in git(repo, "show", "--name-only", "--format=", sha).splitlines() if f.strip()]
        except GitError:
            files = []
        commits.append({"sha": sha, "files": files})
    receipt = port.receipt(plan) if plan else None
    verify = "missing" if receipt is None else ("ok" if receipt.get("ok") else "red")
    prefix = f"p{role['plan']}.{role['name']}.ac"
    behaviours = {k: {"what": v.get("what"), "tests": v.get("tests", []), "status": v.get("status")}
                  for k, v in (port.registry(plan) if plan else {}).items() if k.startswith(prefix)}
    dirty = [line[3:] for line in git(repo, "status", "--porcelain").splitlines()
             if line[3:].strip() and not line[3:].startswith(RECEIPTS)]
    return {"commits": commits, "verify": verify, "behaviours": behaviours, "uncommitted": dirty,
            "base": (plan or {}).get("base")}


def handback(port: PlanStore, sid: str, report: dict[str, Any], commit_judge: CommitJudge, git_judge: GitJudge) -> str:
    """Write the child's receipt on its branch, commit it through the commit gate and push the branch.

    Args:
        port: the ledger port.
        sid: the child's session.
        report: changed, checked, notChecked, risks, testsChanged, and added and faults when there are any.
        commit_judge: the rules' verdict on a commit.
        git_judge: the rules' verdict on a git command.

    Returns:
        What was kept and pushed, and the one message the model sends to the parent.

    Raises:
        WorkError: no child, no card plan, a bad report, not on its branch, a rule stops the commit or the push.
    """
    problems = report_problems(report)
    if problems:
        raise WorkError("The handback was not kept: " + "; ".join(problems))
    ticket, role = mine(port, sid)
    plan = tickets.approved_plan(ticket)
    repo = top(plan["root"]) if plan else None
    if not plan or not repo:
        raise WorkError("take your card first: run('orchestra', 'take')")
    if git(repo, "branch", "--show-current").strip() != role["branch"]:
        raise WorkError(f"stand on your branch {role['branch']} to hand back")
    body = {"name": role["name"], "plan": role["plan"], "draft": role["draft"], "parent": role["parent"],
            "branch": role["branch"], "cardPlan": plan["id"], "at": now(),
            "report": {k: report.get(k, []) for k in LISTS + tuple(PAIRS)}, **facts(port, ticket, role, repo)}
    rel = f"{RECEIPTS}/{role['name']}.json"
    path = Path(repo) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    message = f"Handback of {role['name']} (plan {role['plan']})"
    verdict = commit_judge(repo, [rel], message)
    if stopped(verdict):
        raise WorkError(f"the receipt's commit is stopped: {verdict.reason}")
    sha = commit(repo, [rel], message)
    port.write(lambda con, rec: tickets.save(con, {**tickets.latest(con, sid), "handback": {"sha": sha, "at": now()}}))
    pushed = push(port, sid, git_judge)
    return (f"Handback kept in {rel} on {role['branch']} ({sha[:12]}). {pushed.splitlines()[0]} Now send ONE message "
            f"with send_message to the orchestrator {role['parent']}: \"handed back {role['branch']} {sha}\", and "
            "stop. Do not message it again unless it writes to you.")


def find_receipt(repo: str, name: str) -> Optional[dict[str, Any]]:
    """The receipt of a child in a checkout, for a reader (the parent's check comes in part 3).

    Args:
        repo: the repository's root.
        name: the child's name.

    Returns:
        The receipt, or None when there is none or it does not read.
    """
    try:
        return json.loads((Path(repo) / RECEIPTS / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
