"""The Stop guard (docs 04, section 4): a turn may not end while a code file of the session's plan is changed and no
green verify saw its current content. .md, .json and other files owe nothing. Whatever cannot be read keeps the turn
(fail closed): the detector reports it as owed."""
import os

from harness.utils.git.facts import blob
from harness.utils.plan.verify import dirty

CODE = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".py", ".go", ".java", ".kt", ".rb", ".rs", ".cs", ".php",
        ".vue", ".svelte"}


def is_code(path):
    return os.path.splitext(path)[1].lower() in CODE


def unverified(port, plan):
    """The changed code files of the plan (paths from its root) whose content no green verify saw."""
    green = port.green_receipt(plan)
    seen = green["files"] if green else {}
    return [f for f in dirty(plan) if is_code(f) and seen.get(f) != blob(plan["root"], f)]
