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
import os
import re

from harness.utils.contracts import asked, refused
from harness.utils.git.branches import current
from harness.utils.git.commit import commit
from harness.utils.git.facts import blob, head, top
from harness.utils.plan.files import matches
from harness.utils.plan.grants import test_missing
from harness.utils.plan.tickets import EXECUTE, approved_plan, steps_of
from harness.utils.plan.verify import dirty

LONGEST_MESSAGE = 2000
NO_PLAN = "no plan in force in this session: present one, and the user approves it in the form"
NOT_EXECUTE = "only a step in Execute can be done or skipped (the ticket is in {phase})"


class StepError(ValueError):
    pass


def in_force(port, sid):
    ticket = port.ticket(sid) if sid else None
    plan = approved_plan(ticket)
    if plan is None:
        raise StepError(NO_PLAN)
    if ticket["phase"] != EXECUTE:
        raise StepError(NOT_EXECUTE.format(phase=ticket["phase"]))
    return ticket, {**plan, "grants": port.grants(plan)}


def step_behaviors(plan, n):
    """The behaviours the step n (from 0) owes: its own, or all of them when the plan has no steps."""
    if not plan.get("steps"):
        return list(plan.get("behaviors", []))
    return [b for b in plan.get("behaviors", []) if b.get("step", len(plan["steps"])) == n + 1]


def owed(port, plan, n, files):
    """What the step n still owes before its commit of files (paths from the root): each behaviour of the step active
    with tests that exist (the registry's, else the plan's), every pending or gone behaviour of the plan, and a green
    verify that saw the current content of every file to commit."""
    out, registry = [], port.registry(plan)
    mine = {b["id"] for b in step_behaviors(plan, n)}
    for bid in sorted(mine | set(registry)):
        b = registry.get(bid, {})
        if b.get("status") in ("skipped", "retired"):
            continue
        plan_b = next((x for x in plan.get("behaviors", []) if x["id"] == bid), {})
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
        out.append(f"no green verify: run('verify', 'run', {{'plan': '{plan['plan_id']}'}}) or python3 -m entry.cli verify")
    else:
        moved = [f for f in files if receipt["files"].get(f) != blob(plan["root"], f)]
        if moved:
            out.append(f"changed after the last verify: {', '.join(moved)}")
    return out


def step_done(port, sid, message, judge=None):
    """judge(repo, files, message) -> the verdict of the rules on the commit; None judges nothing (tests of the steps
    alone)."""
    text = str(message or "").strip()
    if not text:
        raise StepError("step-no-message: say what the step's commit does")
    if len(text) > LONGEST_MESSAGE:
        raise StepError(f"the message is longer than {LONGEST_MESSAGE} characters")
    ticket, plan = in_force(port, sid)
    n, steps = ticket["step"], steps_of(plan)
    repo = top(plan["root"])
    if not repo:
        raise StepError(f"the plan's root {plan['root']} is not in a git repository")
    expected = ticket["commits"][-1] if ticket["commits"] else plan.get("base")
    if not expected or head(repo) != expected:
        raise StepError("the repository moved since the approval or the plan's last commit (or had no commit): "
                        "present a new plan")
    fixing = bool(ticket.get("stepCommits", {}).get(str(n)))
    changed_files = dirty(plan)
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
    if port.protected(current(repo)):
        raise StepError(f"step-protected-branch: {current(repo)} is protected; work on a branch of the plan")
    prefix = os.path.relpath(os.path.realpath(plan["root"]), os.path.realpath(repo)).replace("\\", "/")
    paths = [f if prefix == "." else f"{prefix}/{f}" for f in changed_files]
    if judge is not None:
        verdict = judge(repo, paths, text)
        if refused(verdict) or asked(verdict):
            raise StepError(verdict.reason)
    sha = commit(repo, paths, text)
    after = port.step_commit(sid, ticket, plan, repo, sha, fixing)
    head_line = f"Committed {sha[:12]} ({', '.join(changed_files)})."
    if fixing:
        return f"{head_line} The fix is committed; the ticket is in Deliver."
    if after["state"] == "closed":
        return f"{head_line} The last step is done; the plan is delivered and its ticket is closed (no form is asked)."
    if after["phase"] == "execute":
        return f"{head_line} Step {n + 1} is done; step {after['step'] + 1} of {len(steps)} is open."
    return f"{head_line} The last step is done; the ticket is in Deliver."


def step_skip(port, sid, why):
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
