"""Verify: run the unit's test command for an approved plan in its root and keep the receipt: the result and the blob
id of each file of the plan, which the commit gate compares with what is staged. A file that changes while the tests
run is no pass."""
import subprocess
import time

from harness.utils.git.facts import blob
from harness.utils.git.run import GitError

VERIFY_TIMEOUT = 600


def blobs(plan):
    try:
        return {p: blob(plan["root"], p) for p in plan["files"] + plan["tests"]}
    except GitError as e:
        raise ValueError(f"the plan's root is not in a git repository: {e}") from e


def verify(port, command, plan_id):
    """Run the test command (a list of words) for an approved plan and keep the receipt; say whether it passed."""
    plan = port.approved_plan(plan_id)
    if plan is None:
        raise ValueError(f"no approved plan {plan_id} waits for delivery")
    if not command:
        raise ValueError("the config names no verify command")
    started, files = time.monotonic(), blobs(plan)
    try:
        p = subprocess.run(list(command), cwd=plan["root"], capture_output=True, timeout=VERIFY_TIMEOUT)
        code, tail = p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace").strip().splitlines()[-5:]
    except (OSError, subprocess.TimeoutExpired) as e:
        code, tail = -1, [f"{type(e).__name__}: {e}"]
    moved = sorted(p for p, b in blobs(plan).items() if files[p] != b)
    if moved:  # the receipt is for what the tests saw: a file that changed under them is no pass
        tail.append(f"files changed while the tests ran: {', '.join(moved)}")
    ok = code == 0 and not moved
    port.keep_verify(plan, {"files": files, "commands": [list(command)], "code": code, "ok": ok,
                            "why": "\n".join(tail)[-500:], "ms": int((time.monotonic() - started) * 1000)})
    word = "passed" if ok else ("failed" + (f" (exit {code})" if code else ""))
    return f"verify {word} for plan {plan_id}." + ("" if ok else "\n" + "\n".join(tail))
