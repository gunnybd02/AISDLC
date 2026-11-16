"""The Stop guard (docs 04, section 4): a turn may not end while a code file of the session's plan is changed and no
green verify saw its current content. .md, .json and other files owe nothing. Whatever cannot be read keeps the turn
(fail closed): the detector reports it as owed."""
from __future__ import annotations

import os

from harness.utils.git.facts import blob
from harness.utils.plan.verify import dirty
from harness.utils.shapes import ApprovedPlan, PlanStore

CODE = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".py", ".go", ".java", ".kt", ".rb", ".rs", ".cs", ".php",
        ".vue", ".svelte"}


def is_code(path: str) -> bool:
    """Whether a file is code by its extension (CODE); .md, .json and the rest owe nothing.

    Args:
        path: a file path.

    Returns:
        True for an extension of CODE, case ignored.
    """
    return os.path.splitext(path)[1].lower() in CODE


def unverified(port: PlanStore, plan: ApprovedPlan) -> list[str]:
    """The changed code files of the plan (paths from its root) whose content no green verify saw.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        plan: the session's approved plan.

    Returns:
        The paths, in the order dirty() gives them; [] when every changed code file was seen green.

    Raises:
        GitError: git cannot read the plan's root (the detector keeps the turn).
    """
    green = port.green_receipt(plan)
    seen = green["files"] if green else {}
    return [f for f in dirty(plan) if is_code(f) and seen.get(f) != blob(plan["root"], f)]
