"""Merges: the user allows each merge of a pull request (docs/system.md section 12). A merge tool call (TOOL, whatever
its server is named) runs only with a one-use pass for exactly that pull request and head commit: before it, the harness
refuses it and gives the form question (gear/translate/merge.py, the when row merge.no_pass); the user's Allow to that
question writes the pass in pl_asks (accepts); a merge that ran uses it (used), so the next merge asks again. A child
never merges: nobody can answer its form. Merges inside harness actions (orchestra land into the plan branch) are
covered by the plan the user approved."""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Optional

from harness.utils.shapes import PlanStore

TOOL = "__merge_pull_request"  # the GitHub merge tool, whatever its server is named (mcp__github__, mcp__<id>__)
ALLOW_LABEL, NO_LABEL = "Allow", "Deny"  # the labels of the merge form
SHA = re.compile(r"^[0-9a-f]{40}$")
ASKED = re.compile(r"^Merge PR #\d+ of \S+ at [0-9a-f]{12} \[(?P<code>g[0-9a-f]{12})\]\?")
FREE = "SELECT 1 AS x FROM pl_asks WHERE sid = '' AND key = ? AND used = 0"


def target(given: Any) -> Optional[tuple[str, str, int, str]]:
    """The pull request a merge tool call names.

    Args:
        given: the tool's input (owner, repo, pullNumber, expectedHeadSha).

    Returns:
        (owner, repo, number, head sha in lower case, "" when it is no full sha); None when owner, repo or number is
        missing.
    """
    given = given if isinstance(given, dict) else {}
    owner, repo = str(given.get("owner") or "").strip(), str(given.get("repo") or "").strip()
    try:
        number = int(given.get("pullNumber"))
    except (TypeError, ValueError):
        return None
    if not owner or not repo or number <= 0:
        return None
    sha = str(given.get("expectedHeadSha") or "").strip().lower()
    return owner, repo, number, sha if SHA.match(sha) else ""


def code_of(owner: str, repo: str, number: int, sha: str) -> str:
    """The code of one merge: a pull request at one head commit.

    Returns:
        "g" and 12 hex characters of the sha256 of all four (owner and repo in lower case).
    """
    text = json.dumps([owner.lower(), repo.lower(), int(number), sha.lower()])
    return "g" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def question(owner: str, repo: str, number: int, sha: str) -> str:
    """The form question the user answers for one merge.

    Returns:
        "Merge PR #<n> of <owner>/<repo> at <sha12> [<code>]?".
    """
    return f"Merge PR #{number} of {owner}/{repo} at {sha[:12]} [{code_of(owner, repo, number, sha)}]?"


def held(port: PlanStore, code: str) -> bool:
    """Whether an unused pass for this merge is in the ledger.

    Args:
        port: the ledger port.
        code: the merge's code (code_of).

    Returns:
        True when the user allowed it and no merge has used it yet.
    """
    return bool(port.rows(FREE, (code,)))


def accepts(port: PlanStore, answers: dict[str, str]) -> list[str]:
    """Keep the user's Allow to a merge question as a one-use pass of exactly that merge (its code).

    Args:
        port: the ledger port.
        answers: {form question: the label the user chose} of an AskUserQuestion call.

    Returns:
        One GATE note per merge question answered Allow; [] when none was.
    """
    notes = []
    for asked, label in (answers or {}).items():
        found = ASKED.match(str(asked))
        if found and str(label).strip() == ALLOW_LABEL:
            port.write(lambda con, rec, code=found["code"]: con.execute(
                "INSERT OR REPLACE INTO pl_asks (sid, key, at, used) VALUES ('', ?, ?, 0)", (code, int(time.time() * 1000))))
            notes.append(f"GATE: the user allows the merge [{found['code']}]: call the merge tool again, once, with the "
                         "same pull request and expectedHeadSha.")
    return notes


def merged(event: Any) -> str:
    """The "owner/name" a merge tool's answer says was merged; "" for any other call or a merge that failed.

    Args:
        event: a hook call (PostToolUse of a merge tool: input owner, repo; its response).

    Returns:
        "owner/name" in lower case, or "".
    """
    if event.kind != "PostToolUse" or not str(event.tool or "").endswith(TOOL):
        return ""
    text = event.response if isinstance(event.response, str) else json.dumps(event.response)
    flat = (text or "").replace(" ", "").lower()
    if '"merged":true' not in flat and "successfullymerged" not in flat:
        return ""
    owner, repo = str(event.input.get("owner") or ""), str(event.input.get("repo") or "")
    return f"{owner}/{repo}".lower() if owner and repo else ""


def used(port: PlanStore, event: Any) -> list[str]:
    """After a merge tool call that merged: its pass is used, so the next merge asks the user again.

    Args:
        port: the ledger port.
        event: the PostToolUse hook call of any tool.

    Returns:
        [] always: the use is recorded, nothing is told.
    """
    named = target(event.input) if merged(event) else None
    if named and named[3]:
        code = code_of(*named)
        port.write(lambda con, rec: con.execute("UPDATE pl_asks SET used = 1 WHERE sid = '' AND key = ?", (code,)))
    return []
