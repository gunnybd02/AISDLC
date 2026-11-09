"""Act: what the harness writes back after the verdict, and the notes it gives the model.
- The user's answer to the form question of a waiting plan revision: "Duyệt" approves it for the session; any other
  answer approves nothing and asks for a revision.
- After a git commit ran: when HEAD moved off the commit the repository stood on at the approval, the new commit is
  kept and the plan is delivered (a commit that failed leaves HEAD where it was).
- A call with findings: each finding is kept as a rule decision, with the word Claude Code was given."""
from harness.assemble.ports import YES
from harness.utils.contracts import CLAUDE_DECISION
from harness.utils.git_run import head, top

APPROVED = "GATE: the user approved plan {plan} rev {rev} in the form. You may edit its files: {files}."
REFINE = 'GATE: the user did not approve plan {plan} rev {rev}; they answered "{label}". Revise it, then ask again.'
DELIVERED = "GATE: commit {sha} of plan {plan} is kept; the plan is delivered. A new change needs a new plan."


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
                self.port.approve(event.session, waiting, event.cwd)
                notes.append(APPROVED.format(plan=waiting["plan_id"], rev=waiting["rev"],
                                             files=", ".join(waiting["items"]["files"])))
            else:
                notes.append(REFINE.format(plan=waiting["plan_id"], rev=waiting["rev"], label=label.strip()[:200]))
        return notes

    def delivery(self, event, commit, plan):
        repo = top(commit["repo"]) if commit and plan else None
        sha = head(repo) if repo else None
        if not sha or sha == plan.get("base") or self.port.committed(sha):
            return []
        self.port.deliver(event.session, plan, repo, sha)
        return [DELIVERED.format(sha=sha[:12], plan=plan["plan_id"])]
