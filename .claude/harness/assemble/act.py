"""Act: what the harness writes back after the verdict, and the notes it gives the model.
- The user's answer to the form question of a waiting plan revision: "Duyệt" approves it for the session; any other
  answer approves nothing and asks for a revision.
- A call with findings: each finding is kept as a rule decision, with the word Claude Code was given."""
from harness.assemble.ports import YES
from harness.utils.contracts import CLAUDE_DECISION

APPROVED = "GATE: the user approved plan {plan} rev {rev} in the form. You may edit its files: {files}."
REFINE = 'GATE: the user did not approve plan {plan} rev {rev}; they answered "{label}". Revise it, then ask again.'


class Act:
    def __init__(self, port):
        self.port = port

    def run(self, event, facts, verdict):
        notes = []
        answers = facts.get("answers") or {}
        if event.kind == "PostToolUse" and answers:
            for waiting in self.port.waiting():
                label = answers.get(waiting["question"])
                if label is None:
                    continue
                if label.strip() == YES:
                    self.port.approve(event.session, waiting, event.cwd)
                    notes.append(APPROVED.format(plan=waiting["plan_id"], rev=waiting["rev"],
                                                 files=", ".join(waiting["items"]["files"])))
                else:
                    notes.append(REFINE.format(plan=waiting["plan_id"], rev=waiting["rev"], label=label.strip()[:200]))
        for finding in verdict.findings:
            self.port.decision(event, facts.get("plan"), finding, CLAUDE_DECISION.get(verdict.decision, verdict.decision))
        return notes
