"""Closing: a plan is delivered only by what its commit holds, however it was made. HEAD must be a new commit whose
parent is the commit the repository stood on at the approval, and what it changes must be files of the plan, each with
the content the plan's passing verify saw. A HEAD that moved any other way is not the plan's commit: nothing is
delivered, and the model is told."""
import os

from harness.utils.git.facts import committed, head, parent, top

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
