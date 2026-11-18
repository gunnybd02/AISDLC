"""PlanPaths: the files a call writes or names and its shell line, as rule actions with facts; the when rows say
which is refused or asked (spec 13 section 7). The facts (VOCABULARY): kind (write, mention or shell), in_state,
has_plan, in_plan, read_whole, explained, auto. The rows:
- write.state: a write into the harness's own state (its ledger, its maint grant), approved plan or not;
- plan.outside: a write to a file the approved plan does not allow (its file and test patterns, its add file
  grants; a drop grant refuses), under its root;
- read.state: a call that names a place in the harness's own state, read or written by any tool (the shell, Read,
  Grep, Glob...): the ledger is read only through run('ledger', 'db_query');
- shell.unread: a shell call the reader cannot see whole, with the agent's words on what it does, the command, the
  files the reader did see and what it could not read: the user is the one to say;
- shell.unexplained: the same call with no words of the agent that explain it (fewer than three words, or the command
  copied back);
- shell.after: in auto mode (Claude Code's permission mode), the explained call is not asked: the snapshot of each
  repository it may write (utils/shell/after.py) is given as after_before, kept under its call id, and what it changed
  is judged after it ran. Outside a repository, or with no call id, it is asked as in the other modes.
A write with no approved plan is tracked.py's (plan.none). Paths are compared as utils/plan/files.py resolves them."""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Optional

from harness.utils.contracts import RULE_ACTIONS, Event, Translator
from harness.utils.plan.files import allows, holds, relative
from harness.utils.shapes import ApprovedPlan, Facts
from harness.utils.shell.after import Snapshot, snapshot, top_of

LONGEST_COMMAND = 500  # characters of the command shown in the question; Claude Code shows the whole of it too
AUTO = "auto"  # the permission mode in which an unclear command is checked after, not asked


def in_state(path: str, state: Optional[str]) -> bool:
    """Whether a path is inside the harness's own state folder.

    Args:
        path: an absolute path a call writes or names.
        state: the state folder (the fact state_dir), or None/"" when there is none.

    Returns:
        True when state is set and path is in it.
    """
    return bool(state) and relative(path, state) is not None


def allowed(plan: ApprovedPlan, path: str) -> bool:
    """Whether the plan allows the write: a path under its root its patterns or grants allow (utils/plan/files.py), or
    a folder above a planned file (a mkdir of it).

    Args:
        plan: the approved plan, with its root and grants.
        path: the absolute path written.

    Returns:
        True when the write is the plan's.
    """
    rel = relative(path, plan["root"])
    return rel is not None and (allows(plan, rel) or holds(plan, rel))


def plain_words(text: object) -> list[str]:
    """The words of a text, lower case (runs of letters, digits and underscores).

    Args:
        text: any value; it is read as its str().

    Returns:
        The words in order.
    """
    return re.findall(r"\w+", str(text).lower())


def explained(said: str, command: str) -> bool:
    """Whether the agent said in words of its own what the command does: three words at least, not the command.

    Args:
        said: the agent's words on the call (the tool's description).
        command: the shell line.

    Returns:
        True when said has three words or more and its words are not found in the command's.
    """
    words = plain_words(said)
    return len(words) >= 3 and " ".join(words) not in " ".join(plain_words(command))


def shell_detail(facts: Facts) -> str:
    """The words a shell call the reader cannot see whole shows the user: the agent's words, the command (at most
    LONGEST_COMMAND characters), the writes seen and what it could not read.

    Args:
        facts: the call's facts, with shell_unread, and shell_said, shell_command and writes when given.

    Returns:
        The text in brackets of shell.unread.
    """
    said, command, unread = facts.get("shell_said", ""), facts.get("shell_command", ""), facts["shell_unread"]
    shown = command if len(command) <= LONGEST_COMMAND else command[:LONGEST_COMMAND] + "..."
    files = ", ".join(facts.get("writes", [])) or "no file"
    return (f'the agent says: "{said.strip()}"; the command: {shown}; the harness sees it writes: {files}; the part it '
            f'cannot read: {"; ".join(unread)}')


def before_shots(dirs: Sequence[str], plan: Optional[ApprovedPlan]) -> Optional[dict[str, Snapshot]]:
    """The snapshot of each repository an unclear command may write: those of the folders it may run in, and the
    plan's root.

    Args:
        dirs: the folders the line may run in (shell_dirs).
        plan: the approved plan, or None.

    Returns:
        {top folder: snapshot}; None when none of them is in a repository, or one cannot be taken.
    """
    roots = {top_of(d) for d in dirs} | ({top_of(plan["root"])} if plan else set())
    roots.discard("")
    shots = {root: snapshot(root) for root in sorted(roots)}
    if not shots or any(shot is None for shot in shots.values()):
        return None
    return {root: shot for root, shot in shots.items() if shot is not None}


class PlanPaths(Translator):
    """The rule actions of the files a call writes or names, and of a shell line the reader cannot see whole."""
    READS = ("plan", "state_dir", "writes", "mentions", "shell_unread", "shell_said", "shell_command", "shell_dirs")
    VOCABULARY = ("kind", "in_state", "has_plan", "in_plan", "read_whole", "explained", "auto")

    def translate(self, event: Event, facts: Optional[Facts] = None) -> Facts:
        """One action per write (kind write), for the first place of the state a call names that it does not write
        (kind mention), and for a shell line the reader cannot see whole (kind shell, auto when it is checked after:
        its snapshots then come as after_before); {} when there is none."""
        facts = facts or {}
        out: list[dict[str, Any]] = []
        shots = None
        plan, state = facts.get("plan"), facts.get("state_dir")
        for path in facts.get("writes", []):
            inside = in_state(path, state)
            ours = plan is not None and not inside and allowed(plan, path)
            details = {"in_state": path} if inside else \
                {"in_plan": f"{path} is not a file of plan {plan['plan_id']}"} if plan is not None and not ours else {}
            out.append({"kind": "write", "in_state": inside, "has_plan": plan is not None, "in_plan": ours,
                        "details": details})
        written = set(facts.get("writes", []))
        named = next((p for p in facts.get("mentions", []) if p not in written and in_state(p, state)), None)
        if named:
            out.append({"kind": "mention", "in_state": True, "detail": named})
        if facts.get("shell_unread"):
            said = explained(facts.get("shell_said", ""), facts.get("shell_command", ""))
            if said and event.mode == AUTO and event.call:
                shots = before_shots(facts.get("shell_dirs") or [event.cwd], plan)
            out.append({"kind": "shell", "read_whole": False, "explained": said, "auto": shots is not None,
                        "detail": shell_detail(facts) if said else "; ".join(facts["shell_unread"])})
        given: Facts = {RULE_ACTIONS: out} if out else {}
        return {**given, "after_before": shots} if shots is not None else given
