"""Approval: the user's answer to the form question of a waiting plan revision. The approval word approves it for the
session; any other answer approves nothing and asks for a revision. A peer's message never approves: only the answers
of a form, read from its PostToolUse, reach here."""
from harness.utils.contracts import YES

APPROVED = "GATE: the user approved plan {plan} rev {rev} in the form. You may edit its files: {files}."
REFINE = 'GATE: the user did not approve plan {plan} rev {rev}; they answered "{label}". Revise it, then ask again.'


def approvals(port, session, answers):
    """The notes of the user's answers to the form questions of the waiting plan revisions: the approval word approves
    a revision for the session (the only door that opens a plan); any other answer asks for a revision."""
    notes = []
    for waiting in port.waiting() if answers else []:
        label = answers.get(waiting["question"])
        if label is None:
            continue
        if label.strip() == YES:
            port.approve(session, waiting)
            notes.append(APPROVED.format(plan=waiting["plan_id"], rev=waiting["rev"],
                                         files=", ".join(waiting["items"]["files"])))
        else:
            notes.append(REFINE.format(plan=waiting["plan_id"], rev=waiting["rev"], label=label.strip()[:200]))
    return notes
