"""Verify: run the unit's test command for an approved plan in its root and keep the receipt: the result and the blob
id of each file of the plan, which the commit gate compares with what is staged. A file that changes while the tests
run is no pass."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

from harness.utils.git.commit import changed
from harness.utils.git.facts import blob, top
from harness.utils.plan.files import allows, is_pattern
from harness.utils.git.run import GitError
from harness.utils.plan.verify_lock import VerifyLock
from harness.utils.shapes import ApprovedPlan, PlanStore

VERIFY_TIMEOUT = 600
MAX_TIMEOUT = 3600


def dirty(plan: ApprovedPlan) -> list[str]:
    """The paths (from the plan's root) of the files under its root that differ from HEAD and that the plan allows.

    Args:
        plan: the approved plan; its root, files, tests and grants are read.

    Returns:
        The changed paths the plan allows, from its root, sorted as git status gives them.

    Raises:
        ValueError: the plan's root is not in a git repository.
        GitError: git status fails.
    """
    repo = top(plan["root"])
    if not repo:
        raise ValueError(f"the plan's root {plan['root']} is not in a git repository")
    prefix = os.path.relpath(os.path.realpath(plan["root"]), os.path.realpath(repo)).replace("\\", "/")
    out = []
    for path in changed(repo, ["."] if prefix == "." else [prefix]):
        rel = path if prefix == "." else path[len(prefix) + 1:]
        if allows(plan, rel):
            out.append(rel)
    return out


def blobs(plan: ApprovedPlan) -> dict[str, Optional[str]]:
    """{path from the root: blob id or None} of the plan's named files and every changed file it allows.

    Args:
        plan: the approved plan; its root, files, tests and grants are read.

    Returns:
        {path from the plan's root: the blob id git would store, None for a missing file}; patterns left out.

    Raises:
        ValueError: the plan's root is not in a git repository.
    """
    named = [p for p in plan["files"] + plan.get("tests", []) if not is_pattern(p)]
    try:
        return {p: blob(plan["root"], p) for p in dict.fromkeys(named + dirty(plan))}
    except GitError as e:
        raise ValueError(f"the plan's root is not in a git repository: {e}") from e


def run(port: PlanStore, plan: ApprovedPlan, command: Sequence[str], timeout: float = VERIFY_TIMEOUT,
        cwd: Optional[str | Path] = None) -> tuple[bool, int, list[str], list[str]]:
    """Run command (a list of words, no shell, stdin closed) for the approved plan under the verify lock, without the
    harness's own variables (project_env); keep the receipt (ok, exit code, last lines, changed files). The tests get
    no ledger: one that records builds its own home (docs/12-ledger.md).
    Exit 124: the timeout ended it; 127: it could not start. A file that changed while it ran makes it red.

    Args:
        port: the harness ledger (plans, tickets, audit rows); the receipt is kept in it.
        plan: the approved plan with its grants.
        command: the test command's words.
        timeout: the seconds the command may run.
        cwd: the folder it runs in; None for the plan's root.

    Returns:
        (ok, exit code, the last 25 lines of its output, the changed files the plan allows); the receipt is kept.

    Raises:
        ValueError: no command, or the plan's root is not in a git repository.
        LockTimeout: another verify held the lock too long.
    """
    if not command:
        raise ValueError("no verify command: the config names none and none was given")
    folder = cwd or plan["root"]
    started = time.monotonic()
    with VerifyLock(folder):
        files, changed = blobs(plan), dirty(plan)
        env = project_env()
        try:
            p = subprocess.run(list(command), cwd=folder, capture_output=True, timeout=timeout, env=env,
                               stdin=subprocess.DEVNULL)
            code, out = p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            code, out = 124, f"the run passed its timeout of {timeout} s"
        except OSError as e:
            code, out = 127, f"the command cannot start: {e}"
        tail = out.strip().splitlines()[-25:]
        moved = sorted(p for p, b in blobs(plan).items() if files.get(p) != b)
    if moved and code == 0:  # the receipt is for what the tests saw: a file that changed under them is no pass
        tail.append(f"a file changed while the tests ran: {', '.join(moved)}")
    ok = code == 0 and not moved
    port.keep_verify(plan, {"files": files, "commands": [list(command)], "code": code, "ok": ok,
                            "why": (tail[-1] if tail else "")[-500:] if not ok else "",
                            "ms": int((time.monotonic() - started) * 1000)})
    return ok, code, tail, changed



HARNESS_ENV = ("HARNESS_HOME", "HARNESS_CODE", "HARNESS_SESSION")


def project_env() -> dict[str, str]:
    """The environment a project's tests run with: this process's, without the variables that point at the harness
    in force (its home, its release, its session). With them, a test that starts a harness entry would write to the
    live home's ledger (found by orchestra's live run: a child's verify left test plans in its live ledger).

    Returns:
        A copy of os.environ without HARNESS_ENV.
    """
    return {k: v for k, v in os.environ.items() if k not in HARNESS_ENV}


NOTHING_TO_RUN = ["{python}", "-c", "pass"]  # a plan with no tests: its files' receipt is kept, no test runs


def command_of(plan: ApprovedPlan, default: Sequence[str]) -> list[str]:
    """The test command of a plan: its own (from the repo its root is in, or a child's unit: set by the server, never
    by the model), else default (a command the caller was given); a plan with no tests and no command runs nothing,
    so its receipt is still kept; "{python}" is this Python.

    Args:
        plan: the plan in force.
        default: a command given by the caller ([] for none).

    Returns:
        The command's words; [] for a plan with tests that names no command.
    """
    words = plan.get("verify") or list(default) or ([] if plan.get("tests") else NOTHING_TO_RUN)
    return [sys.executable if w == "{python}" else w for w in words]


def verify(port: PlanStore, command: Sequence[str], plan_id: str) -> str:
    """The MCP door: run the test command for the approved plan plan_id and say whether it passed.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        command: a test command the caller gives ([] for none: the plan's own runs, command_of).
        plan_id: the desk id (pd-...) of the plan in force.

    Returns:
        The text for the model: "verify passed for plan <id>." or "verify failed (exit N) ..." with the last 5 lines.

    Raises:
        ValueError: no plan in force has that desk id, no command, or its root is not in a git repository.
        LockTimeout: another verify held the lock too long.
    """
    plan = port.approved_plan(plan_id)
    if plan is None:
        raise ValueError(f"no approved plan {plan_id} waits for delivery")
    command = command_of(plan, command)
    if not command:
        raise ValueError("no test command: the plan has tests, and the repo its folder is in names no verify; "
                         "add the repo with its verify to the plan's repos")
    ok, code, tail, _ = run(port, {**plan, "grants": port.grants(plan)}, command)
    word = "passed" if ok else ("failed" + (f" (exit {code})" if code else ""))
    return f"verify {word} for plan {plan_id}." + ("" if ok else "\n" + "\n".join(tail[-5:]))
