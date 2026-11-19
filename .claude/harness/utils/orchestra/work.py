"""Work: what a child session does (docs/05b-orchestra-cloud.md part 2), each through the ledger port and git, never
through the model's shell.

- take: open the card plan, approved by the grant of the parent plan (no form), on the child's own branch.
- push: push the child's own branch, judged by the git rules; it pushes after every step, since its machine dies.
- ask: a question for the parent, committed as a numbered note on the child's branch and pushed; then the child stops.
- handback: the child's report and what harness code reads itself (commits, verify, behaviours, uncommitted files),
  written as .harness/handback/<name>.json, committed through the commit gate and pushed with the branch.

A child sends no message and gets none: a cloud child cannot message its parent (auto mode refuses it, the other
modes wait for an approval nobody gives; live checks of 2026-11-17). Parent and child talk through the branch."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional

from harness.utils.contracts import asked, now, refused
from harness.utils.git.commit import commit
from harness.utils.git.facts import head, top
from harness.utils.git.run import GitError, git, run_git
from harness.utils.orchestra import child
from harness.utils.orchestra.brief import NOTES, child_subject
from harness.utils.orchestra.catchup import CatchUpError, taken
from harness.utils.plan import tickets
from harness.utils.plan.ship import audit
from harness.utils.shapes import ChildRole, CommitJudge, GitJudge, PlanStore, Ticket

if TYPE_CHECKING:
    from harness.utils.ledger.recorder import Recorder

RECEIPTS = ".harness/handback"
STOP = "Then stop: end your turn. You send no message; the orchestrator reads your branch."
LISTS = ("changed", "checked", "notChecked", "risks")
PAIRS = {"testsChanged": ("test", "why"), "added": ("file", "why"), "faults": ("what", "where")}
MOST, LONGEST, LONGEST_PAIR = 10, 200, 400
NO_CHILD = ("this session is no child: only a session opened from an orchestrator's brief takes a card (its first "
            "prompt starts 'You are child session')")


class WorkError(ValueError):
    """A child's action refuses; the message says why and what to do."""


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


def switch(repo: str, name: str, base: str = "") -> str:
    """Stand on the branch name: the local one, else the remote one tracked, else a new one from origin/<base> (the
    unit's base, so its pull request holds only the child's commits), else a new one from HEAD.

    Args:
        repo: the repository's root.
        name: the branch.
        base: the unit's base branch; "" for HEAD.

    Returns:
        How the branch was reached: "on", "tracked", "new from origin/<base>" or "new from HEAD".

    Raises:
        GitError: git refuses (uncommitted changes in the way, among others).
    """
    if git(repo, "branch", "--list", name).strip():
        git(repo, "switch", "-q", name)
        return "on"
    try:
        remote = git(repo, "ls-remote", "--heads", "origin", name).strip()
    except GitError:
        remote = ""  # no origin, or it cannot be reached: the branch starts here
    if remote:
        git(repo, "fetch", "-q", "origin", name)
        git(repo, "switch", "-q", "-c", name, "--track", f"origin/{name}")
        return "tracked"
    if base:
        try:
            git(repo, "fetch", "-q", "origin", base, timeout=300)
            git(repo, "switch", "-q", "-c", name, "FETCH_HEAD")
            return f"new from origin/{base}"
        except GitError:
            pass  # the base is not on origin: the branch starts here
    git(repo, "switch", "-q", "-c", name)
    return "new from HEAD"


def stopped(verdict: Any) -> bool:
    """Whether the rules stop an action: a refusal, or a question nobody in a child can answer.

    Args:
        verdict: the rules' Verdict.

    Returns:
        True when it is refused or asked.
    """
    return refused(verdict) or asked(verdict)


def take(port: PlanStore, sid: str, root: str, first: Optional[Callable[[str], Any]] = None) -> str:
    """Open the child's card plan, approved by the grant of its parent plan, on its own branch.

    Args:
        port: the ledger port.
        sid: the child's session.
        root: the folder the session works in (the repository is the one holding it).
        first: first(repo) commits the registration on the branch before the plan opens (register.on_branch) and
            gives its record {issue, sha}, which the approval names; None, or a None record, names none.

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
        how = switch(repo, role["branch"], role.get("start") or role.get("unit", {}).get("base", ""))
    except GitError as e:
        raise WorkError(f"git cannot stand on {role['branch']}: {e}") from e
    folder = child.unit_root(role, repo)
    if not Path(folder).is_dir():
        raise WorkError(f"the unit's folder {role['unit']['path']} is not in this clone ({repo})")
    notes = sorted(p.relative_to(repo).as_posix() for p in (Path(repo) / NOTES / role["name"]).glob("*.md"))
    record = first(repo) if first else None  # the registration, committed before the plan's base is taken
    plan_id, _, _ = port.present(child.card_plan(role, folder), sid=sid)
    by = f"grant of plan {role['plan']} ({role['parent']})" + (
        f", registration #{record['issue']} in {record['sha'][:12]}" if record else "")
    number = port.approve(sid, port.revision(plan_id), by=by)
    return (f"Card plan {plan_id} (plan {number}) is open, approved by the grant of plan {role['plan']}; you are on "
            f"{role['branch']} ({how}). Files: {', '.join(role['card']['change'])}. Behaviours: "
            f"{', '.join(role['behaviours'])}. Loop: write the tests, make them pass, verify bare, "
            "run('plan', 'step_done', {message}), run('orchestra', 'push'); then run('orchestra', 'handback', {...})."
            + (f" Notes on your branch, read them first: {', '.join(notes)}." if notes else ""))


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
    try:  # the orchestrator's note commits on origin first (live run 4), so the push is a fast-forward
        took = taken(port, sid, repo, role["branch"], role["name"])
    except CatchUpError as e:
        raise WorkError(str(e)) from e
    verdict = judge(repo, ["push", "-u", "origin", role["branch"]])
    if stopped(verdict):
        raise WorkError(verdict.reason)
    code, out = run_git(repo, ["push", "-u", "origin", role["branch"]])
    if code != 0:
        raise WorkError(f"git push failed (exit {code}): {out.strip()[-500:]}")
    audit(port, sid, ticket, "push", repo, role["branch"], head(repo))
    return (f"{took}\n" if took else "") + f"Pushed {role['branch']} ({(head(repo) or '')[:12]}) to origin.\n{out.strip()[-600:]}"


def ask(port: PlanStore, sid: str, question: str, commit_judge: CommitJudge, git_judge: GitJudge) -> str:
    """Write a question of the child for its parent as a numbered note on its branch, commit it and push the branch.

    Args:
        port: the ledger port.
        sid: the child's session.
        question: one question, at most 400 characters.
        commit_judge: the rules' verdict on a commit.
        git_judge: the rules' verdict on a git command.

    Returns:
        Where the question is, and that the child stops now.

    Raises:
        WorkError: no child, an empty or too long question, no card plan, not on its branch, or a rule stops the
            commit or the push.
    """
    text = " ".join(str(question).split())
    if not text or len(text) > LONGEST_PAIR:
        raise WorkError(f"a question is one to {LONGEST_PAIR} characters")
    ticket, role = mine(port, sid)
    repo = on_branch(ticket, role, "put a question")
    n = len(ticket.get("asks", [])) + 1
    rel = f"{NOTES}/{role['name']}/question-{n}.md"
    path = Path(repo) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Question {n} from {role['name']} (plan {role['plan']})\n\n{text}\n", encoding="utf-8")
    message = child_subject(role, f"Question {n} of {role['name']} (plan {role['plan']})")
    verdict = commit_judge(repo, [rel], message)
    if stopped(verdict):
        raise WorkError(f"the question's commit is stopped: {verdict.reason}")
    sha = commit(repo, [rel], message)

    def change(con: sqlite3.Connection, rec: Recorder) -> None:
        fresh = tickets.latest(con, sid)
        tickets.save(con, {**fresh, "asks": list(fresh.get("asks", [])) + [{"n": n, "text": text, "at": now(),
                                                                            "sha": sha}]})
    port.write(change)
    pushed = push(port, sid, git_judge)
    return (f"Question {n} is in {rel} on {role['branch']} ({sha[:12]}). {pushed.splitlines()[0]} {STOP} The "
            "orchestrator answers with a note on your branch, and a fresh session goes on from there.")


def on_branch(ticket: Ticket, role: ChildRole, what: str) -> str:
    """The repository of the child's card plan, when the child stands on its branch.

    Args:
        ticket: the child's ticket.
        role: its child role.
        what: what it does, for the message ("put a question", "hand back").

    Returns:
        The repository's root.

    Raises:
        WorkError: no card plan in force, or another branch checked out.
    """
    plan = tickets.approved_plan(ticket)
    repo = top(plan["root"]) if plan else None
    if not plan or not repo:
        raise WorkError("take your card first: run('orchestra', 'take')")
    if git(repo, "branch", "--show-current").strip() != role["branch"]:
        raise WorkError(f"stand on your branch {role['branch']} to {what}")
    return repo


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
        {commits: [{sha, files}], verify: ok/red/missing, behaviours: {id: {what, tests, status}}, uncommitted,
        refused (each step the harness refused because nobody could answer, once), base}.
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
    refused = [r["detail"] for r in port.rows("SELECT detail FROM act_rule_decisions WHERE sid = ? AND rule = ? "
                                               "ORDER BY at", (ticket["sid"], "child.no_keyboard"))]
    return {"commits": commits, "verify": verify, "behaviours": behaviours, "uncommitted": dirty,
            "refused": list(dict.fromkeys(refused)), "base": (plan or {}).get("base")}


def handback(port: PlanStore, sid: str, report: dict[str, Any], commit_judge: CommitJudge, git_judge: GitJudge,
             store_on: bool = False) -> str:
    """Write the child's receipt on its branch, commit it through the commit gate and push the branch.

    Args:
        port: the ledger port.
        sid: the child's session.
        report: changed, checked, notChecked, risks, testsChanged, and added and faults when there are any.
        commit_judge: the rules' verdict on a commit.
        git_judge: the rules' verdict on a git command.
        store_on: whether a store folder is set; then the child saves its ledger to the store before it stops
            (the parent's plan is done only when every child's database is there).

    Returns:
        What was kept and pushed, and that the child stops now.

    Raises:
        WorkError: no child, no card plan, a bad report, not on its branch, a rule stops the commit or the push.
    """
    problems = report_problems(report)
    if problems:
        raise WorkError("The handback was not kept: " + "; ".join(problems))
    ticket, role = mine(port, sid)
    repo = on_branch(ticket, role, "hand back")
    plan = tickets.approved_plan(ticket)
    body = {"name": role["name"], "plan": role["plan"], "draft": role["draft"], "parent": role["parent"],
            "session": sid,  # the child's own id as its harness knows it (its store copies are named by it)
            "branch": role["branch"], "unit": {"name": role["card"].get("unit"), **role.get("unit", {})},
            "cardPlan": plan["id"], "at": now(),
            "report": {k: report.get(k, []) for k in LISTS + tuple(PAIRS)}, **facts(port, ticket, role, repo)}
    rel = f"{RECEIPTS}/{role['name']}.json"
    path = Path(repo) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    message = child_subject(role, f"Handback of {role['name']} (plan {role['plan']})")
    verdict = commit_judge(repo, [rel], message)
    if stopped(verdict):
        raise WorkError(f"the receipt's commit is stopped: {verdict.reason}")
    sha = commit(repo, [rel], message)
    port.write(lambda con, rec: tickets.save(con, {**tickets.latest(con, sid), "handback": {"sha": sha, "at": now()}}))
    pushed = push(port, sid, git_judge)
    save = ("Save your ledger to the store: run('ledger', 'export', {reason: 'handback'}) and upload the copy as its "
            "answer says (guide('store', 'skills')). " if store_on else "")
    return f"Handback kept in {rel} on {role['branch']} ({sha[:12]}). {pushed.splitlines()[0]} {save}{STOP}"


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
