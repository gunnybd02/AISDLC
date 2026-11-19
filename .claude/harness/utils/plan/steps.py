"""Steps (docs 04, section 6): step_done {message} commits the current step of the session's plan, then opens the next;
the last step moves the ticket to deliver, and a home plan then closes delivered with no form (close_home). The
harness is the one writer of these commits. Refused, in order:
- step-no-message: no message;            - no plan in force, or the ticket is not in execute;
- the repository moved: HEAD is not the commit of the approval or the plan's own last commit;
- step-nothing-to-commit: no changed file the plan allows (step_skip gives a step up);
- step-other-files: a changed file only another step names (not when fixing);
- step-owed: a behaviour of the step without its test, a test file that is gone, no green verify, or a file changed
  after the last verify;
- step-protected-branch: the branch is protected;
- the commit guards (judge: the rules on the commit, gear/detect/secret.py, mark.py, agent.py): a secret in an
  added line, an AI mark or a banned word in the message, agent files in a unit's commit.
A fix: the step was committed, the ticket went back to execute (a write in deliver), and plan files changed again.
step_skip {why} gives the current step up: its behaviours are kept skipped, and the ticket moves on (no close)."""
from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Optional

from harness.utils.contracts import asked, refused
from harness.utils.orchestra.brief import child_subject
from harness.utils.git.branches import current
from harness.utils.git.commit import commit
from harness.utils.git.facts import blob, head, top
from harness.utils.git.run import GitError, git
from harness.utils.plan.files import matches
from harness.utils.plan.grants import test_missing
from harness.utils.plan import tickets
from harness.utils.plan.tickets import EXECUTE, steps_of
from harness.utils.plan.verify import dirty
from harness.utils.shapes import ApprovedPlan, CommitJudge, PlanBehaviour, PlanStore, Step, Ticket

LONGEST_MESSAGE = 2000
NO_PLAN = "no plan in force in this session: present one, and the user approves it in the form"
NOT_EXECUTE = "only a step in Execute can be done or skipped (the ticket is in {phase})"


class StepError(ValueError):
    """step_done or step_skip refuses; the message starts with the refusal's code where it has one."""


def in_force(port: PlanStore, sid: str) -> tuple[Ticket, ApprovedPlan]:
    """The session's ticket and its plan in force, in execute.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        sid: the Claude Code session id.

    Returns:
        (the ticket, its plan with its grants).

    Raises:
        StepError: no plan in force, or the ticket is not in execute.
    """
    found = tickets.in_force(port, sid)
    if found is None:
        raise StepError(NO_PLAN)
    if found[0]["phase"] != EXECUTE:
        raise StepError(NOT_EXECUTE.format(phase=found[0]["phase"]))
    return found


def step_behaviors(plan: ApprovedPlan, n: int) -> list[PlanBehaviour]:
    """The behaviours the step n (from 0) owes: its own, or all of them when the plan has no steps.

    Args:
        plan: the plan in force.
        n: the step's index, from 0.

    Returns:
        The plan's behaviours of step n + 1 (one with no step belongs to the last step).
    """
    if not plan.get("steps"):
        return list(plan.get("behaviors", []))
    return [b for b in plan.get("behaviors", []) if b.get("step", len(plan["steps"])) == n + 1]


def owed(port: PlanStore, plan: ApprovedPlan, n: int, files: Sequence[str]) -> list[str]:
    """What the step n still owes before its commit of files (paths from the root): each behaviour of the step active
    with tests that exist (the registry's, else the plan's), every pending or gone behaviour of the plan but those of
    later steps (their tests come with their step), and a green verify that saw the current content of every file to
    commit.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        plan: the plan in force with its grants.
        n: the step's index, from 0.
        files: the files to commit, from the plan's root.

    Returns:
        One line per debt; [] when the step owes nothing.
    """
    out, registry = [], port.registry(plan)
    mine = {b["id"] for b in step_behaviors(plan, n)}
    for bid in sorted(mine | set(registry)):
        b = registry.get(bid, {})
        if b.get("status") in ("skipped", "retired"):
            continue
        plan_b = next((x for x in plan.get("behaviors", []) if x["id"] == bid), {})
        if bid not in mine and int(b.get("step") or plan_b.get("step") or 0) > n + 1:
            continue  # a behaviour of a later step: its test is written when that step comes
        tests = b.get("tests") or ([plan_b["test"]] if plan_b.get("test") else [])
        if bid in mine and not tests:
            out.append(f"behaviour {bid} has no test: add one with add test")
            continue
        for test in tests:
            missing = test_missing(plan["root"], test)
            if missing:
                out.append(f"behaviour {bid}: its test {test} is not written yet ({missing})" if bid in mine or
                           b.get("status") == "pending" else f"behaviour {bid}: its test {test} is gone ({missing})")
    receipt = port.receipt(plan)
    if not receipt or not receipt.get("ok"):
        out.append(f"no green verify: run('verify', 'run', {{'plan': '{plan['plan_id']}'}}) or, from the shell, the anchor's cli verify")
    else:
        moved = [f for f in files if receipt["files"].get(f) != blob(plan["root"], f)]
        if moved:
            out.append(f"changed after the last verify: {', '.join(moved)}")
    return out


def step_done(port: PlanStore, sid: str, message: Optional[str], judge: Optional[CommitJudge] = None) -> str:
    """Commit the current step of the session's plan (or adopt the commits git.commit made) and open the next.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        sid: the Claude Code session id.
        message: the step's commit message.
        judge: judge(repo, files, message) -> the verdict of the rules on the commit; None judges nothing (tests of
            the steps alone).

    Returns:
        The text for the model: what was committed or adopted, and which step is open or that the plan is delivered.

    Raises:
        StepError: a refusal of the list above, with its code.
        GitError: git fails while committing.
    """
    text = str(message or "").strip()
    if not text:
        raise StepError("step-no-message: say what the step's commit does")
    if len(text) > LONGEST_MESSAGE:
        raise StepError(f"the message is longer than {LONGEST_MESSAGE} characters")
    ticket, plan = in_force(port, sid)
    text = child_subject(ticket.get("child") or {}, text)  # "#N <name>: ...": the forge links it to the issue
    n, steps = ticket["step"], steps_of(plan)
    repo = top(plan["root"])
    if not repo:
        raise StepError(f"the plan's root {plan['root']} is not in a git repository")
    noted = ticket.get("noted", [])
    expected = (ticket["commits"] + noted)[-1] if ticket["commits"] + noted else plan.get("base")
    for move in ticket.get("caughtUp") or []:  # the harness took in the orchestrator's notes (orchestra/catchup.py)
        expected = move.get("to") if move.get("from") == expected else expected
    if not expected or head(repo) != expected:
        raise StepError("the repository moved since the approval or the plan's last commit (or had no commit): "
                        "present a new plan")
    fixing = bool(ticket.get("stepCommits", {}).get(str(n)))
    changed_files = dirty(plan)
    if not changed_files and noted:  # the step's commits were made by git.commit: adopt them once proven
        problems = owed(port, plan, n, [])
        unproven = [f for sha in noted for f in committed_files(repo, plan, sha)
                    if (port.green_receipt(plan) or {}).get("files", {}).get(f) != blob(plan["root"], f)]
        if problems or unproven:
            raise StepError("step-unproven: " + "; ".join(problems + ([f"no green verify saw {', '.join(unproven)}"]
                                                                      if unproven else [])))
        after = port.step_commit(sid, ticket, plan, repo, None, False)
        return done_text(after, n, steps, f"Adopted {', '.join(s[:12] for s in noted)}.")
    if not changed_files:
        raise StepError("step-nothing-to-commit: no changed file the plan allows (give the step up with step_skip)")
    mine = steps[n].get("files", []) + steps[n].get("tests", [])
    others = [p for i, s in enumerate(steps) if i != n for p in s.get("files", []) + s.get("tests", [])]
    granted = {p for op, p in plan.get("grants", []) if op == "add"}
    other = [] if fixing or not plan.get("steps") else [
        f for f in changed_files if f not in granted and not matches(mine, f) and matches(others, f)]
    if other:
        raise StepError(f"step-other-files: {', '.join(other)} belong to another step: commit them there")
    problems = owed(port, plan, n, changed_files)
    if problems:
        raise StepError("step-owed: " + "; ".join(problems))
    if port.protected(current(repo), repo):
        raise StepError(f"step-protected-branch: {current(repo)} is protected; work on a branch of the plan")
    prefix = os.path.relpath(os.path.realpath(plan["root"]), os.path.realpath(repo)).replace("\\", "/")
    paths = [f if prefix == "." else f"{prefix}/{f}" for f in changed_files]
    if judge is not None:
        verdict = judge(repo, paths, text)
        if refused(verdict) or asked(verdict):
            raise StepError(verdict.reason)
    sha = commit(repo, paths, text)
    after = port.step_commit(sid, ticket, plan, repo, sha, fixing)
    upkeep = getattr(port, "upkeep", None)
    if upkeep:
        upkeep()  # the ledger's upkeep runs after a commit; it never raises and is once a day in effect
    head_line = f"Committed {sha[:12]} ({', '.join(changed_files)})."
    if fixing:
        return f"{head_line} The fix is committed; the ticket is in Deliver."
    return done_text(after, n, steps, head_line)


def done_text(after: Ticket, n: int, steps: list[Step], head_line: str) -> str:
    """The text of a done step.

    Args:
        after: the ticket after the step's commit.
        n: the index of the step done, from 0.
        steps: the plan's steps.
        head_line: the first sentence (what was committed or adopted).

    Returns:
        head_line and what comes next: the plan delivered, the next step open, or the ticket in deliver.
    """
    if after["state"] == "closed":
        return f"{head_line} The last step is done; the plan is delivered and its ticket is closed (no form is asked)."
    if after["phase"] == "execute":
        return f"{head_line} Step {n + 1} is done; step {after['step'] + 1} of {len(steps)} is open."
    return f"{head_line} The last step is done; the ticket is in Deliver: push it (git.push) and open its merge request."


def committed_files(repo: str, plan: ApprovedPlan, sha: str) -> list[str]:
    """The files (from the plan's root) the commit sha changes.

    Args:
        repo: the repository's root.
        plan: the plan in force; its root is read.
        sha: the commit.

    Returns:
        The changed paths under the plan's root, from it; [] when git fails.
    """
    prefix = os.path.relpath(os.path.realpath(plan["root"]), os.path.realpath(repo)).replace("\\", "/")
    try:
        names = git(repo, "show", "--name-only", "--format=", sha).split()
    except GitError:
        return []
    return [n if prefix == "." else n[len(prefix) + 1:] for n in names if prefix == "." or n.startswith(prefix + "/")]


def step_skip(port: PlanStore, sid: str, why: Optional[str]) -> str:
    """Give the current step up: its behaviours are kept skipped and the ticket moves on.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        sid: the Claude Code session id.
        why: the reason, one line of at most 200 characters.

    Returns:
        The text for the model: the step given up and which step is open, or that the ticket is in deliver.

    Raises:
        StepError: a bad reason, no plan in force, not in execute, or plan files are changed.
    """
    text = str(why or "").strip()
    if not text or "\n" in text or len(text) > 200:
        raise StepError("why is one line of at most 200 characters")
    ticket, plan = in_force(port, sid)
    if dirty(plan):
        raise StepError("plan files are changed: commit them with step_done, or put them back, before a skip")
    n = ticket["step"]
    after = port.step_skip(sid, ticket, plan, [b["id"] for b in step_behaviors(plan, n)], text)
    if after["phase"] == "execute":
        return f"Step {n + 1} is given up ({text}); step {after['step'] + 1} is open."
    return f"Step {n + 1} is given up ({text}); the ticket is in Deliver."
