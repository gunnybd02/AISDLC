"""The Stop guard (docs 04, section 4): a turn may not end while a code file of the session's plan is changed and no
green verify saw its current content. .md, .json and other files owe nothing. Whatever cannot be read keeps the turn
(fail closed): the detector reports it as owed. A file another writer changed after the last green verify (the session's
own writes are in the ledger, utils/ledger/writes.py) is named in a note and does not hold the turn."""
from __future__ import annotations

import os
from typing import Callable

from harness.utils.git.facts import blob
from harness.utils.plan.verify import dirty
from harness.utils.shapes import ApprovedPlan, PlanStore

FOREIGN = ("GATE: {files} changed after your last green verify, but this session did not make that change (another "
           "writer did), so the turn is not held for it. Run the verify again before you rely on it.")
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


def foreign(port: PlanStore, plan: ApprovedPlan, written: dict[str, set[str]]) -> list[str]:
    """The unverified code files another writer changed: the last green verify saw content this session wrote, and
    the file now holds content this session did not write. A file with no recorded write is never one of them.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        plan: the session's approved plan.
        written: {real path: the hashes of every content the session wrote} (utils/ledger/writes.written).

    Returns:
        The paths from the plan's root, in the order unverified() gives them.

    Raises:
        GitError: git cannot read the plan's root.
    """
    green = port.green_receipt(plan)
    seen, out = (green["files"] if green else {}), []
    for path in unverified(port, plan):
        mine = written.get(os.path.realpath(os.path.join(plan["root"], path)).replace("\\", "/"), set())
        if seen.get(path) and seen[path] in mine and (blob(plan["root"], path) or "") not in mine:
            out.append(path)
    return out


def owed(port: PlanStore, plan: ApprovedPlan, written: dict[str, set[str]]) -> list[str]:
    """The code files that hold the turn: unverified, and not changed by another writer.

    Args:
        port: the harness ledger (plans, tickets, audit rows).
        plan: the session's approved plan.
        written: {real path: the hashes of every content the session wrote}.

    Returns:
        The paths from the plan's root.

    Raises:
        GitError: git cannot read the plan's root (the detector keeps the turn).
    """
    others = set(foreign(port, plan, written))
    return [path for path in unverified(port, plan) if path not in others]


def foreign_note(look: Callable[[ApprovedPlan], list[str]], plan: ApprovedPlan) -> list[str]:
    """The note for the model about files another writer changed; it never holds the turn.

    Args:
        look: plan -> the files another writer changed (the port's stop_foreign).
        plan: the session's approved plan.

    Returns:
        [the note] when there are such files; [] when there are none or the harness could not look.
    """
    try:
        files = look(plan)
    except Exception:
        return []
    return [FOREIGN.format(files=", ".join(files))] if files else []
