"""Verify: run the unit's test command for an approved plan in its root and keep the receipt: the result and the blob
id of each file of the plan, which the commit gate compares with what is staged. A file that changes while the tests
run is no pass."""
import os
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

from harness.utils.git.commit import changed
from harness.utils.git.facts import blob, top
from harness.utils.plan.files import allows, is_pattern
from harness.utils.git.run import GitError
from harness.utils.plan.verify_lock import VerifyLock

VERIFY_TIMEOUT = 600
MAX_TIMEOUT = 3600


def dirty(plan):
    """The paths (from the plan's root) of the files under its root that differ from HEAD and that the plan allows."""
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


def blobs(plan):
    """{path from the root: blob id or None} of the plan's named files and every changed file it allows."""
    named = [p for p in plan["files"] + plan["tests"] if not is_pattern(p)]
    try:
        return {p: blob(plan["root"], p) for p in dict.fromkeys(named + dirty(plan))}
    except GitError as e:
        raise ValueError(f"the plan's root is not in a git repository: {e}") from e


def sandbox(ledger_path, folder):
    """A copy of the live ledger (sqlite backup) in folder, for the tests to open instead of it; None without one."""
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


def run(port, plan, command, timeout=VERIFY_TIMEOUT, cwd=None):
    """Run command (a list of words, no shell, stdin closed) for the approved plan under the verify lock, with
    HARNESS_DB set to a copy of the live ledger; keep the receipt. (ok, exit code, last lines, changed files).
    Exit 124: the timeout ended it; 127: it could not start. A file that changed while it ran makes it red."""
    if not command:
        raise ValueError("no verify command: the config names none and none was given")
    folder = cwd or plan["root"]
    started = time.monotonic()
    with VerifyLock(folder), tempfile.TemporaryDirectory(prefix="harness-verify-") as tmp:
        files, changed = blobs(plan), dirty(plan)
        copy = sandbox(port.path, tmp)
        env = {**os.environ, **({"HARNESS_DB": str(copy)} if copy else {})}
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


def verify(port, command, plan_id):
    """The MCP door: run the test command for the approved plan plan_id and say whether it passed."""
    plan = port.approved_plan(plan_id)
    if plan is None:
        raise ValueError(f"no approved plan {plan_id} waits for delivery")
    ok, code, tail, _ = run(port, {**plan, "grants": port.grants(plan)}, command)
    word = "passed" if ok else ("failed" + (f" (exit {code})" if code else ""))
    return f"verify {word} for plan {plan_id}." + ("" if ok else "\n" + "\n".join(tail[-5:]))
