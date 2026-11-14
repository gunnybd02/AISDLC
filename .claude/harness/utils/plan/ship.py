"""Shipping a plan's change (docs 04, section 6): git.commit commits named files of the plan (the step does not move:
step_done then adopts the commit), git.push pushes the plan's branch of a unit in deliver, git.mr_open opens its merge
request after the user's Yes on the full text. Each is refused with a code and why; push and merge request are kept in
pl_git_audit (chained)."""
import hashlib
import json
import os
import re
import time
import uuid

from harness.utils.contracts import asked, refused
from harness.utils.git.asks import take
from harness.utils.git.branches import current
from harness.utils.git.commit import commit
from harness.utils.git.facts import blob, head, top
from harness.utils.git.gitlab import GitLabError, open_mr, project_of
from harness.utils.git.marks import banned_in, marks_in
from harness.utils.git.run import GitError, git, run_git
from harness.utils.plan.files import allows
from harness.utils.plan.stop import is_code
from harness.utils.plan.tickets import DELIVER, approved_plan

ALLOW_LABEL, NO_LABEL = "Cho ph\u00e9p", "Kh\u00f4ng"
MR_HEAD = "M\u1edf MR"
MR_RE = re.compile("^M\u1edf MR .+ \\[(?P<code>m[0-9a-f]{12})\\]\\?")


class ShipError(ValueError):
    pass


def in_force(port, sid):
    ticket = port.ticket(sid) if sid else None
    plan = approved_plan(ticket)
    if plan is None:
        raise ShipError("git-commit-no-plan: no plan in force in this session; present a light plan")
    return ticket, {**plan, "grants": port.grants(plan)}


def git_commit(port, sid, files, message, judge):
    """Commit the named files (paths from the plan's root) of the session's plan."""
    if not isinstance(files, list) or not files or not all(isinstance(f, str) and f.strip() for f in files):
        raise ShipError("files is a list of paths from the plan's root")
    text = str(message or "").strip()
    if not text:
        raise ShipError("the message is empty")
    ticket, plan = in_force(port, sid)
    repo = top(plan["root"])
    if not repo:
        raise ShipError(f"the plan's root {plan['root']} is not in a git repository")
    if port.protected(current(repo)):
        raise ShipError(f"git-commit-protected-branch: {current(repo)} is protected")
    rels = []
    for f in files:
        rel = os.path.normpath(f).replace("\\", "/")
        if rel in (".", "") or rel.startswith("..") or os.path.isabs(f) or os.path.isdir(os.path.join(plan["root"], rel)):
            raise ShipError(f"{f}: name files from the plan's root, never ., a folder or a path outside it")
        if not allows(plan, rel):
            raise ShipError(f"git-commit-outside-plan: {rel} is not a file of the plan")
        rels.append(rel)
    green = port.green_receipt(plan)
    unverified = [r for r in rels if is_code(r) and (green or {}).get("files", {}).get(r) != blob(plan["root"], r)]
    if unverified:
        raise ShipError(f"git-commit-unverified: {', '.join(unverified)} changed since the last green verify")
    prefix = os.path.relpath(os.path.realpath(plan["root"]), os.path.realpath(repo)).replace("\\", "/")
    paths = [r if prefix == "." else f"{prefix}/{r}" for r in rels]
    verdict = judge(repo, paths, text)
    if refused(verdict) or asked(verdict):
        raise ShipError(verdict.reason)
    sha = commit(repo, paths, text)
    port.note_commit(sid, plan, repo, sha)
    return f"Committed {sha[:12]} ({', '.join(rels)}). The step does not move: call step_done to end it."


def git_push(port, sid, judge):
    ticket, plan = in_force(port, sid)
    repo = top(plan["root"])
    if not repo:
        raise ShipError(f"the plan's root {plan['root']} is not in a git repository")
    if port.is_home(repo):
        raise ShipError("git-home-never-pushes: the home, the repository of the harness, never pushes")
    if ticket["phase"] != DELIVER:
        raise ShipError(f"git-push-wrong-phase: a plan pushes in Deliver, after its last step (it is in {ticket['phase']})")
    branch = current(repo)
    if not branch or port.protected(branch):
        raise ShipError(f"git-push-protected-branch: {branch or 'a detached HEAD'} is not a branch of the plan")
    verdict = judge(repo, ["push", "-u", "origin", branch])
    if refused(verdict) or asked(verdict):
        raise ShipError(verdict.reason)
    code, out = run_git(repo, ["push", "-u", "origin", branch])
    if code != 0:
        raise ShipError(f"git push failed (exit {code}): {out.strip()[-500:]}")
    audit(port, sid, ticket, "push", repo, branch, head(repo))
    return f"Pushed {branch} ({head(repo)[:12]}) to origin.\n{out.strip()[-1000:]}"


def mr_code(repo, branch, target, title, description):
    return "m" + hashlib.sha256(json.dumps([str(repo), branch, target, title, description]).encode()).hexdigest()[:12]


def mr_open(port, sid, title, description, target, banned=()):
    ticket, plan = in_force(port, sid)
    repo = top(plan["root"])
    title, description = str(title or "").strip(), str(description or "").strip()
    if not title or "\n" in title or len(title) > 200 or not description:
        raise ShipError("a merge request has a one-line title (200 characters at most) and a description")
    marks = marks_in(title + "\n" + description) + [f"the banned word {w}" for w in banned_in(title + " " + description, banned)]
    if marks:
        raise ShipError(f"the merge request text holds {', '.join(marks)}: write it as the author of the change")
    branch = current(repo) if repo else ""
    try:
        pushed = git(repo, "rev-parse", f"origin/{branch}").strip()
    except GitError:
        pushed = ""
    if not branch or pushed != head(repo):
        raise ShipError(f"push {branch or 'the branch'} first (git.push): the merge request opens on what origin holds")
    code = mr_code(repo, branch, target, title, description)
    if not take(port, code):
        q = f'{MR_HEAD} {branch} \u2192 {target}: "{title}" [{code}]?\n{description}'
        return (f"The user confirms the full text first. Ask now with AskUserQuestion, one question, exactly:\n{q}\n"
                f"Options: \"{ALLOW_LABEL}\", \"{NO_LABEL}\". Never fill in the answer. Then run mr_open again with the "
                f"same text.")
    try:
        api, project = project_of(git(repo, "remote", "get-url", "origin").strip())
        mr = open_mr(api, project, branch, target, title, description)
    except (GitLabError, GitError) as e:
        raise ShipError(f"the merge request was not opened: {e}") from e
    audit(port, sid, ticket, "mr", repo, branch, head(repo), remote_ref=str(mr.get("web_url", "")))
    return f"Merge request !{mr.get('iid')} opened: {mr.get('web_url')}"


def mr_accepts(port, answers):
    """Keep the user's Yes to a merge request form as a one-use pass of exactly that text (its code)."""
    notes = []
    for q, label in (answers or {}).items():
        m = MR_RE.match(str(q))
        if m and str(label).strip() == ALLOW_LABEL:
            port.write(lambda con, rec, code=m["code"]: con.execute(
                "INSERT OR REPLACE INTO pl_asks (sid, key, at, used) VALUES ('', ?, ?, 0)", (code, int(time.time() * 1000))))
            notes.append(f"GATE: the user confirms the merge request [{m['code']}]; run mr_open again, once.")
    return notes


def audit(port, sid, ticket, kind, repo, branch, sha, remote_ref=None):
    port.write(lambda con, rec: rec.insert(con, "pl_git_audit", {
        "uid": uuid.uuid4().hex, "sid": sid, "kind": kind, "tickets": json.dumps([ticket["id"]]), "repo": repo,
        "local_ref": branch, "base": ticket["plan"].get("base"), "source": "mcp", "sha": sha, "remote": "origin",
        "remote_ref": remote_ref or branch, "remote_sha": sha, "files": "[]", "at": int(time.time() * 1000)}))
