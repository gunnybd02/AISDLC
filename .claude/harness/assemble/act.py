"""Act: what the harness writes back after the verdict, and the notes it gives the model.
- The user's answer to the form question of a waiting plan revision: "Duyệt" approves it for the session; any other
  answer approves nothing and asks for a revision.
- After a git command in the plan's own repository: the plan is delivered only by what the commit holds, however it
  was made. HEAD must be a new commit whose parent is the commit the repository stood on at the approval, and what it
  changes must be files of the plan, each with the content the plan's passing verify saw. A HEAD that moved any other
  way is not the plan's commit: nothing is delivered, and the model is told.
- A call with findings: each finding is kept as a rule decision, with the word Claude Code was given."""
import os

from harness.utils.contracts import CLAUDE_DECISION, YES
from harness.utils.git_run import committed, head, parent, top

APPROVED = "GATE: the user approved plan {plan} rev {rev} in the form. You may edit its files: {files}."
REFINE = 'GATE: the user did not approve plan {plan} rev {rev}; they answered "{label}". Revise it, then ask again.'
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


class Act:
    def __init__(self, port):
        self.port = port

    def run(self, event, facts, verdict):
        notes = []
        if event.kind == "PostToolUse":
            notes += self.approvals(event, facts.get("answers") or {})
            notes += self.delivery(event, facts.get("git_commit"), facts.get("plan"))
        for finding in verdict.findings:
            self.port.decision(event, facts.get("plan"), finding, CLAUDE_DECISION.get(verdict.decision, verdict.decision))
        return notes

    def approvals(self, event, answers):
        notes = []
        for waiting in self.port.waiting() if answers else []:
            label = answers.get(waiting["question"])
            if label is None:
                continue
            if label.strip() == YES:
                self.port.approve(event.session, waiting)
                notes.append(APPROVED.format(plan=waiting["plan_id"], rev=waiting["rev"],
                                             files=", ".join(waiting["items"]["files"])))
            else:
                notes.append(REFINE.format(plan=waiting["plan_id"], rev=waiting["rev"], label=label.strip()[:200]))
        return notes

    def delivery(self, event, commit, plan):
        repo = top(plan["root"]) if commit and plan else None
        sha = head(repo) if repo else None
        if not sha or sha == plan.get("base") or self.port.committed(sha):
            return []
        why = self.not_the_plans(repo, sha, plan)
        if why:
            return [NOT_DELIVERED.format(sha=sha[:12], plan=plan["plan_id"], why=why)]
        self.port.deliver(event.session, plan, repo, sha)
        return [DELIVERED.format(sha=sha[:12], plan=plan["plan_id"])]

    def not_the_plans(self, repo, sha, plan):
        """Why the commit sha is not the plan's verified change, or ""."""
        if not plan.get("base"):
            return "the repository had no commit at the approval: make a first commit, then a new plan"
        if parent(repo, sha) != plan["base"]:
            return "it is not made right on the commit of the approval"
        receipt = self.port.receipt(plan)
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
