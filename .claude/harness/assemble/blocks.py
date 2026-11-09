"""The blocks `run` reaches, with their handlers. They live in assemble because they write through its ports; mcp
only serves them.
- plan: plan_present keeps a plan and gives the form question the model asks with AskUserQuestion; plan_status.
- verify: run the unit's test command (the config's verify) in the plan's root and keep the receipt: the result and
  the blob id of each file of the plan, which the commit gate compares with what is staged."""
import re
import subprocess
import time

from harness.assemble.config import Config
from harness.assemble.ports import LedgerPort
from harness.utils.git_run import GitError, blob

VERIFY_TIMEOUT = 600

PLAN_KEYS = ("title", "files", "tests")
ABSOLUTE = re.compile(r"^([A-Za-z]:|[\\/])")


def paths(value, name, required):
    if not isinstance(value, list) or not all(isinstance(p, str) and p.strip() for p in value) or (required and not value):
        raise ValueError(f"{name} is a list of paths" + (", at least one" if required else ""))
    for p in value:
        if ABSOLUTE.match(p) or ".." in re.split(r"[\\/]", p):
            raise ValueError(f"{name}: {p} is not a path inside the repository (relative, no ..)")
    return [p.replace("\\", "/") for p in value]


def checked(plan):
    if not isinstance(plan, dict) or set(plan) - set(PLAN_KEYS):
        raise ValueError(f"a plan holds only {', '.join(PLAN_KEYS)}")
    if not isinstance(plan.get("title"), str) or not plan["title"].strip():
        raise ValueError("a plan has a title")
    return {"title": plan["title"].strip(), "files": paths(plan.get("files"), "files", True),
            "tests": paths(plan.get("tests", []), "tests", False)}


def add_plan(table, port: LedgerPort):
    table.add_block("plan", "Present a plan; the user approves it in the form, and only its files may change")

    def present(plan):
        plan_id, rev, q = port.present(checked(plan))
        return (f"Plan {plan_id} rev {rev} waits for the user's approval. Ask it now with AskUserQuestion, one "
                f'question, exactly: {q} Options: "Duyệt", "Sửa plan". Never fill in the answer.')

    def status():
        waiting = port.waiting()
        if not waiting:
            return "No plan waits for an approval."
        return "\n".join(f"{w['plan_id']} rev {w['rev']} waits: {w['items']['title']}" for w in waiting)

    table.add("plan", "plan_present", "Keep a plan {title, files, tests} and give the form question", {"plan": "object"},
              present)
    table.add("plan", "plan_status", "The plans that wait for an approval", {}, status)


def verify(port, claude_dir, plan_id):
    """Run the test command for an approved plan and keep the receipt; say whether it passed."""
    plan = port.approved_plan(plan_id)
    if plan is None:
        raise ValueError(f"no approved plan {plan_id} waits for delivery")
    command = Config.load(claude_dir).verify
    if not command:
        raise ValueError("the config names no verify command")
    started = time.monotonic()
    try:
        p = subprocess.run(list(command), cwd=plan["root"], capture_output=True, timeout=VERIFY_TIMEOUT)
        code, tail = p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace").strip().splitlines()[-5:]
    except (OSError, subprocess.TimeoutExpired) as e:
        code, tail = -1, [f"{type(e).__name__}: {e}"]
    try:
        files = {p: blob(plan["root"], p) for p in plan["files"] + plan["tests"]}
    except GitError as e:
        raise ValueError(f"the plan's root is not in a git repository: {e}") from e
    ok = code == 0
    port.keep_verify(plan, {"files": files, "commands": [list(command)], "code": code, "ok": ok,
                            "why": "\n".join(tail)[-500:], "ms": int((time.monotonic() - started) * 1000)})
    word = "passed" if ok else f"failed (exit {code})"
    return f"verify {word} for plan {plan_id}." + ("" if ok else "\n" + "\n".join(tail))


def add_verify(table, port, claude_dir):
    table.add_block("verify", "Run the unit's tests for an approved plan; a commit needs a passing verify")
    table.add("verify", "run", "Run the test command in the plan's root and keep the receipt", {"plan": "string"},
              lambda plan: verify(port, claude_dir, plan))
