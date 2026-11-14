"""Closing: a plan is delivered only by what its commit holds, however it was made. HEAD must be a new commit whose
parent is the commit the repository stood on at the approval, and what it changes must be files of the plan, each with
the content the plan's passing verify saw. A HEAD that moved any other way is not the plan's commit: nothing is
delivered, and the model is told."""
import os
import re

from harness.utils.git.facts import committed, head, parent, top
from harness.utils.git.run import GitError, git
from harness.utils.plan.files import allows, is_pattern
from harness.utils.plan.tickets import approved_plan

DELIVERED = "GATE: commit {sha} of plan {plan} is kept; the plan is delivered. A new change needs a new plan."
NOT_DELIVERED = "GATE: HEAD {sha} is not the verified change of plan {plan} ({why}); the plan is not delivered."
FILE_MODES = ("100644", "100755")  # a plain file, as the verify saw it; not a link, a submodule or a type change


def git_path(path):
    """A path as git names it in a tree: forward slashes, no . or .., case kept (a tree is case-sensitive)."""
    return os.path.normpath(path).replace("\\", "/")


def from_repo(repo, root, paths):
    """{path from the repository root: value} for {path from the plan's root: value}."""
    prefix = os.path.relpath(os.path.realpath(root), os.path.realpath(repo))
    return {git_path(os.path.join(prefix, p)): v for p, v in paths.items()}


def delivery(port, session, commit, plan):
    """The note of a git command in the plan's own repository: delivered, not delivered (why), or nothing."""
    if plan and plan.get("steps"):  # a plan of steps is committed by step_done only, step by step
        return []
    repo = top(plan["root"]) if commit and plan else None
    sha = head(repo) if repo else None
    if not sha or sha == plan.get("base") or port.committed(sha):
        return []
    why = not_the_plans(port, repo, sha, plan)
    if why:
        return [NOT_DELIVERED.format(sha=sha[:12], plan=plan["plan_id"], why=why)]
    port.deliver(session, plan, repo, sha)
    return [DELIVERED.format(sha=sha[:12], plan=plan["plan_id"])]


def not_the_plans(port, repo, sha, plan):
    """Why the commit sha is not the plan's verified change, or ""."""
    if not plan.get("base"):
        return "the repository had no commit at the approval: make a first commit, then a new plan"
    if parent(repo, sha) != plan["base"]:
        return "it is not made right on the commit of the approval"
    receipt = port.receipt(plan)
    if not receipt or not receipt.get("ok"):
        return "the plan has no passing verify"
    seen = from_repo(repo, plan["root"], receipt["files"])
    changes = committed(repo, plan["base"], sha)
    if not changes:
        return "it changes nothing"
    for path, (old, mode, blob_id) in changes.items():
        name = git_path(path)
        if name not in seen:
            return f"it changes {path}, which is no file of the plan"
        if seen[name] != blob_id:
            return f"{path} is not what the verify saw"
        if blob_id is not None and mode not in FILE_MODES:
            return f"{path} becomes a {mode} entry, not a plain file"
        if old is not None and mode is not None and old != mode:
            return f"{path} changes its mode ({old} to {mode})"
    return ""


# The close form (docs 04, section 6): plan_close never closes; it gives the exact question with the facts of the
# ledger, and only the user's answer closes: \u0110\u00e3 giao (delivered), B\u1ecf plan (abandoned); Gi\u1eef m\u1edf or a note keeps it open.
CLOSE_RE = re.compile("^\u0110\u00f3ng plan \"(?P<title>.*)\" \\((?P<draft>pd-[^)]+)\\) \\[(?P<ticket>t-[^\\]]+)\\]\\?")
DELIVER_LABEL, ABANDON_LABEL, KEEP_LABEL = "\u0110\u00e3 giao", "B\u1ecf plan", "Gi\u1eef m\u1edf"
CLOSED = "GATE: plan {draft} is closed {reason} by the user's form; its ticket is closed."
KEPT = "GATE: the user keeps plan {draft} open ({label})."
LONGEST = 200


def close_facts(port, ticket, plan):
    """The lines of the close form, from the ledger and git only."""
    repo = top(plan["root"])
    changed = []
    for sha in ticket["commits"]:
        changed += [p for p in git_names(repo, sha) if p not in changed] if repo else []
    prefix = os.path.relpath(os.path.realpath(plan["root"]), os.path.realpath(repo)).replace("\\", "/") if repo else "."
    rel = [p if prefix == "." else p[len(prefix) + 1:] for p in changed if prefix == "." or p.startswith(prefix + "/")]
    unplanned = [p for p in rel if not allows(plan, p)]
    untouched = [p for p in plan["files"] + plan["tests"] if not is_pattern(p) and p not in rel]
    receipt = port.receipt(plan)
    skipped = sorted(b for b, e in port.registry(plan).items() if e["status"] == "skipped")
    lines = [f"Commit: {', '.join(s[:12] for s in ticket['commits']) or 'none'}",
             f"Files vs plan: changed {len(rel)}, unplanned {', '.join(unplanned) or 'none'}, untouched "
             f"{', '.join(untouched) or 'none'}",
             f"Verify: {'none' if not receipt else 'green' if receipt['ok'] else 'RED'}"]
    return lines + ([f"SKIPPED: {', '.join(skipped)}"] if skipped else [])


def git_names(repo, sha):
    try:
        return [n for n in git(repo, "show", "--name-only", "--format=", sha).splitlines() if n.strip()]
    except GitError:
        return []


def close_question(port, sid, summary=None, exceptions=None):
    """What the model asks to close the session's plan; raises ValueError with why it cannot be asked."""
    for text in [summary] + list(exceptions or []):
        if text is not None and (not isinstance(text, str) or "\n" in text or len(text) > LONGEST):
            raise ValueError(f"a summary or an exception is one line of at most {LONGEST} characters")
    ticket = port.ticket(sid) if sid else None
    if not ticket or ticket["state"] != "open":
        raise ValueError("no open ticket in this session")
    plan = approved_plan(ticket)
    if plan is None:
        raise ValueError("no plan in force in this session")
    lines = ([f"Summary: {summary}"] if summary else []) + close_facts(port, ticket, {**plan, "grants": port.grants(plan)})
    lines += [f"Exceptions: {'; '.join(exceptions)}"] if exceptions else []
    q = f'\u0110\u00f3ng plan "{plan["title"]}" ({plan["plan_id"]}) [{ticket["id"]}]?\n' + "\n".join(lines)
    return (f"Ask the user now with AskUserQuestion, one question, exactly:\n{q}\nOptions: \"{DELIVER_LABEL}\", "
            f"\"{ABANDON_LABEL}\", \"{KEEP_LABEL}\". Never fill in the answer.")


def close_answers(port, sid, answers):
    """Close the session's ticket on the user's answer to its close form; the notes for the model."""
    notes = []
    for q, label in (answers or {}).items():
        m = CLOSE_RE.match(str(q))
        ticket = port.ticket(sid) if m else None
        if not m or not ticket or ticket["id"] != m["ticket"] or ticket["state"] != "open":
            continue
        label = str(label).strip()
        reason = {DELIVER_LABEL: "delivered", ABANDON_LABEL: "abandoned"}.get(label)
        if reason is None:
            notes.append(KEPT.format(draft=m["draft"], label=label[:200]))
            continue
        port.close_plan(sid, ticket, reason, str(q).split("\n")[1:])
        notes.append(CLOSED.format(draft=m["draft"], reason=reason))
    return notes
