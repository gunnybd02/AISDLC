"""Approval: the user's answer to the form question of a waiting plan revision. The approval word approves it for the
session; any other answer approves nothing, is kept as feedback and asks for a revision. A peer's message never approves: only the answers
of a form, read from its PostToolUse, reach here."""
from __future__ import annotations

from harness.utils.contracts import YES
from harness.utils.orchestra import crew
from harness.utils.shapes import PlanStore

APPROVED = "GATE: the user approved plan {plan} rev {rev} in the form. You may edit its files: {files}."
BLOCKED = "GATE: plan {plan} rev {rev} was not opened: {why}."
REFINE = 'GATE: the user did not approve plan {plan} rev {rev}; they answered "{label}". Revise it, then ask again.'


def approvals(port: PlanStore, session: str, answers: dict[str, str]) -> list[str]:
    """The notes of the user's answers to the form questions of the waiting plan revisions: the approval word approves
    a revision for the session (the only door that opens a plan); any other answer asks for a revision.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        session: the Claude Code session id that asked the form.
        answers: {form question: the label the user chose} of an AskUserQuestion call.

    Returns:
        One APPROVED, BLOCKED (a delegated plan runs in the session) or REFINE note per waiting revision whose
        question was answered.
    """
    notes = []
    for waiting in port.waiting() if answers else []:
        label = answers.get(waiting["question"])
        if label is None:
            continue
        busy = crew.blocks_other(port.ticket(session), waiting["plan_id"]) if label.strip() == YES else ""
        if busy:
            notes.append(BLOCKED.format(plan=waiting["plan_id"], rev=waiting["rev"], why=busy))
        elif label.strip() == YES:
            port.approve(session, waiting)
            notes.append(APPROVED.format(plan=waiting["plan_id"], rev=waiting["rev"],
                                         files=", ".join(waiting["items"]["files"])))
        else:
            port.feedback(waiting["plan_id"], waiting["rev"], session, label.strip()[:300])
            notes.append(REFINE.format(plan=waiting["plan_id"], rev=waiting["rev"], label=label.strip()[:300]))
    return notes
