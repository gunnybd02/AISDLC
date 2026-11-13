"""The blocks `run` reaches, with their handlers. They live in assemble because they write through its ports; mcp
only serves them.
- plan: plan_present keeps a plan and gives the form question the model asks with AskUserQuestion; plan_status.
- verify: run the unit's test command (the config's verify) in the plan's root and keep the receipt: the result and
  the blob id of each file of the plan, which the commit gate compares with what is staged.
- harness: pause gives the form question that, answered "Duyệt" by the user, pauses the guards (entry/hook.py holds
  the pause itself, so it works when the harness is broken); pause_status reads state/pause.json."""
import json
import os
import re
import subprocess
import time
from pathlib import Path

from harness.assemble.engine.config import Config
from harness.assemble.engine.ports import LedgerPort
from harness.utils.git.facts import blob
from harness.utils.git.run import GitError

VERIFY_TIMEOUT = 600

PLAN_KEYS = ("title", "files", "tests")
ABSOLUTE = re.compile(r"^([A-Za-z]:|[\\/])")


def paths(value, name, required):
    if not isinstance(value, list) or not all(isinstance(p, str) and p.strip() for p in value) or (required and not value):
        raise ValueError(f"{name} is a list of paths" + (", at least one" if required else ""))
    for p in value:
        parts = [s.lower() for s in re.split(r"[\\/]", p)]
        if ABSOLUTE.match(p) or ".." in parts:
            raise ValueError(f"{name}: {p} is not a path inside the repository (relative, no ..)")
        if ".git" in parts:
            raise ValueError(f"{name}: {p} is inside .git, which no plan edits")
        if any(mark in p for mark in "~%,"):
            raise ValueError(f"{name}: {p} holds ~, % or a comma, which the shell or the form would read otherwise")
    return [p.replace("\\", "/") for p in value]


def checked(plan):
    if not isinstance(plan, dict) or set(plan) - set(PLAN_KEYS):
        raise ValueError(f"a plan holds only {', '.join(PLAN_KEYS)}")
    if not isinstance(plan.get("title"), str) or not plan["title"].strip() or '"' in plan["title"]:
        raise ValueError("a plan has a title, without double quotes (the form question quotes it)")
    return {"title": plan["title"].strip(), "files": paths(plan.get("files"), "files", True),
            "tests": paths(plan.get("tests", []), "tests", False),
            "root": os.getcwd().replace("\\", "/")}  # the MCP server runs in the project's folder


def add_plan(table, port: LedgerPort):
    table.add_block("plan", "Present a plan; the user approves it in the form, and only its files may change")

    def present(plan, plan_id=None):
        """A new plan, or with plan_id a new revision of a plan that waits for its approval."""
        items = checked(plan)
        if plan_id is not None and plan_id not in {w["plan_id"] for w in port.waiting()}:
            raise ValueError(f"no plan {plan_id} waits for an approval: present a new plan without plan_id")
        plan_id, rev, q = port.present(items, plan_id)
        return (f"Plan {plan_id} rev {rev} waits for the user's approval. Ask it now with AskUserQuestion, one "
                f'question, exactly: {q} Options: "Duyệt", "Sửa plan". Never fill in the answer.')

    def status():
        waiting = port.waiting()
        if not waiting:
            return "No plan waits for an approval."
        return "\n".join(f"{w['plan_id']} rev {w['rev']} waits: {w['items']['title']}" for w in waiting)

    table.add("plan", "plan_present", "Keep a plan {title, files, tests} and give the form question; plan_id makes a "
              "new revision of a waiting plan", {"plan": "object", "plan_id?": "string"}, present)
    table.add("plan", "plan_status", "The plans that wait for an approval", {}, status)


def blobs(plan):
    try:
        return {p: blob(plan["root"], p) for p in plan["files"] + plan["tests"]}
    except GitError as e:
        raise ValueError(f"the plan's root is not in a git repository: {e}") from e


def verify(port, claude_dir, plan_id):
    """Run the test command for an approved plan and keep the receipt; say whether it passed."""
    plan = port.approved_plan(plan_id)
    if plan is None:
        raise ValueError(f"no approved plan {plan_id} waits for delivery")
    command = Config.load(claude_dir).verify
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


MAX_PAUSE = 120


def pause_question(minutes, why):
    if not isinstance(minutes, int) or not 1 <= minutes <= MAX_PAUSE:
        raise ValueError(f"minutes is a whole number from 1 to {MAX_PAUSE}")
    why = " ".join(str(why).split()).rstrip("?")
    if not why:
        raise ValueError("say why the guards should pause")
    q = f"Tắt guard {minutes} phút: {why}?"
    return (f"Ask the user now with AskUserQuestion, one question, exactly: {q} Options: \"Duyệt\", \"Không\". Never "
            f"fill in the answer. Only the user's Duyệt pauses the guards; every call is traced while they are paused.")


def pause_status(claude_dir):
    try:
        pause = json.loads((Path(claude_dir) / "state" / "pause.json").read_text(encoding="utf-8"))
        left = int(float(pause["until"]) - time.time())
    except (OSError, ValueError, KeyError, TypeError):
        return "The guards are on."
    return f"The guards are paused for {left // 60} more minutes: {pause.get('why')}." if left > 0 else "The guards are on."


def add_harness(table, claude_dir):
    table.add_block("harness", "The guards themselves: pause them for a while, only through the user's form")
    table.add("harness", "pause", "The form question that pauses the guards for N minutes (1 to 120)",
              {"minutes": "number", "why": "string"}, pause_question)
    table.add("harness", "pause_status", "Whether the guards are paused, and for how long", {},
              lambda: pause_status(claude_dir))


def add_verify(table, port, claude_dir):
    table.add_block("verify", "Run the unit's tests for an approved plan; a commit needs a passing verify")
    table.add("verify", "run", "Run the test command in the plan's root and keep the receipt", {"plan": "string"},
              lambda plan: verify(port, claude_dir, plan))
