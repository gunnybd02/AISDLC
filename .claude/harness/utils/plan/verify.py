"""Verify: run the unit's test command for an approved plan in its root and keep the receipt: the result and the blob
id of each file of the plan, which the commit gate compares with what is staged. A file that changes while the tests
run is no pass."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
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


def sandbox(ledger_path: str | Path, folder: str | Path) -> Optional[Path]:
    """A copy of the live ledger (sqlite backup) in folder, for the tests to open instead of it; None without one.

    Args:
        ledger_path: the live ledger's file.
        folder: the folder the copy goes to (a temp folder).

    Returns:
        <folder>/harness.db, or None when there is no live ledger.
    """
    if not Path(ledger_path).is_file():
        return None
    copy = Path(folder) / "harness.db"
    src, dst = sqlite3.connect(f"{Path(ledger_path).resolve().as_uri()}?mode=ro", uri=True), sqlite3.connect(copy)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    return copy


def run(port: PlanStore, plan: ApprovedPlan, command: Sequence[str], timeout: float = VERIFY_TIMEOUT,
        cwd: Optional[str | Path] = None) -> tuple[bool, int, list[str], list[str]]:
    """Run command (a list of words, no shell, stdin closed) for the approved plan under the verify lock, with
    HARNESS_DB set to a copy of the live ledger and without the harness's own variables (project_env); keep the
    receipt (ok, exit code, last lines, changed files).
    Exit 124: the timeout ended it; 127: it could not start. A file that changed while it ran makes it red.

    Args:
        port: the harness ledger (plans, tickets, audit rows); its path is copied for the tests.
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
    with VerifyLock(folder), tempfile.TemporaryDirectory(prefix="harness-verify-") as tmp:
        files, changed = blobs(plan), dirty(plan)
        copy = sandbox(port.path, tmp)
        env = {**project_env(), **({"HARNESS_DB": str(copy)} if copy else {})}
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


def command_of(plan: ApprovedPlan, default: Sequence[str]) -> list[str]:
    """The test command of a plan: its own (a child's card plan carries its unit's verify, set by the server, never
    by the model), else default, the config's; "{python}" is this Python.

    Args:
        plan: the plan in force.
        default: the config's verify command.

    Returns:
        The command's words; [] when neither names one.
    """
    words = plan.get("verify") or list(default)
    return [sys.executable if w == "{python}" else w for w in words]


def verify(port: PlanStore, command: Sequence[str], plan_id: str) -> str:
    """The MCP door: run the test command for the approved plan plan_id and say whether it passed.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        command: the config's test command (a plan that carries its own runs that one: command_of).
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
        raise ValueError("no verify command: the config names none")
    ok, code, tail, _ = run(port, {**plan, "grants": port.grants(plan)}, command)
    word = "passed" if ok else ("failed" + (f" (exit {code})" if code else ""))
    return f"verify {word} for plan {plan_id}." + ("" if ok else "\n" + "\n".join(tail[-5:]))
