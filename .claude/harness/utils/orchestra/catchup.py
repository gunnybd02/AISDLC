"""Catch-up: a running child takes in the orchestrator's note commits on its branch (live run 4). The parent's reject
and answer push a note commit (.harness/notes/<name>/) on the child's branch as the record, and send the signed order
(orders.py); the child's copy of the branch lacks that commit, and a child may not pull. So its harness does it: at a
valid fix or answer (caught_up, from orders.arrived) and before each push (work.push), it takes in exactly the commits
that change only the child's notes folder: a fast-forward, or the child's own unpushed commits replayed on top. Any
other commit on origin is refused and nothing changes. Each move it makes is kept in the child's ticket (MOVES:
from, to), so step_done takes it as the harness's own and not as a foreign change (live run 5)."""
from __future__ import annotations

from typing import Any

from harness.utils.contracts import now
from harness.utils.git.facts import head, top
from harness.utils.git.run import GitError, git, run_git
from harness.utils.orchestra.brief import NOTES
from harness.utils.plan import tickets
from harness.utils.shapes import PlanStore

MOVES = "caughtUp"  # the child's ticket: [{from, to, at}], each move catch_up made (utils/plan/steps.py follows them)


class CatchUpError(ValueError):
    """The child's branch cannot take in what origin holds: a commit that is not the orchestrator's note, or its own
    commits could not be replayed on the notes. Nothing was changed."""


def caught_up(port: PlanStore, sid: str, role: dict[str, Any]) -> list[str]:
    """After a valid fix or answer: the child's branch takes in the orchestrator's note commits at once (catch_up), so
    the note it is told to read is in its tree.

    Returns:
        The line catch_up gave, or why it could not; [] when there was nothing to take in.
    """
    plan = tickets.approved_plan(port.ticket(sid))
    repo = top(plan["root"]) if plan else None
    if not repo:
        return []
    try:
        took = taken(port, sid, repo, role["branch"], role["name"])
    except CatchUpError as e:
        return [f"Your branch could not take in the orchestrator's notes: {e}"]
    return [took] if took else []


def taken(port: PlanStore, sid: str, repo: str, branch: str, name: str) -> str:
    """catch_up, and the move it made kept in the child's ticket (MOVES), so the next step_done accepts it.

    Args:
        port: the ledger port.
        sid: the child's session.
        repo: the child's clone.
        branch: its branch.
        name: the child's name.

    Returns:
        What catch_up gave.

    Raises:
        CatchUpError: as catch_up.
    """
    before = head(repo)
    took = catch_up(repo, branch, name)
    after = head(repo)
    if before and after and before != after:
        def keep(con: Any, rec: Any) -> None:
            fresh = tickets.latest(con, sid)
            tickets.save(con, {**fresh, MOVES: list(fresh.get(MOVES) or []) + [{"from": before, "to": after,
                                                                                 "at": now()}]})
        port.write(keep)
    return took


def catch_up(repo: str, branch: str, name: str) -> str:
    """Take in the commits origin holds on the child's branch that the child does not have, when each changes only
    the child's notes folder (NOTES/<name>/: the orchestrator's send-backs and answers): a fast-forward, or the child's
    own unpushed commits replayed on top of them. Live run 4: a push refused for want of the note commit left the
    child stuck, as a child may not pull.

    Args:
        repo: the child's clone.
        branch: its branch (orch/p<plan>/<name>).
        name: the child's name.

    Returns:
        What was taken in, or "" when origin holds nothing new (or the branch is not on origin yet).

    Raises:
        CatchUpError: a commit on origin changes another file, or the replay stops; nothing was changed.
    """
    code, _ = run_git(repo, ["fetch", "-q", "origin", branch])
    if code != 0:
        return ""
    try:
        extra = git(repo, "rev-list", "--reverse", "HEAD..FETCH_HEAD").split()
        folder = f"{NOTES}/{name}/"
        foreign = [sha[:12] for sha in extra if any(not f.startswith(folder) for f in git(
            repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).split())]
        ahead = git(repo, "rev-list", "FETCH_HEAD..HEAD").split()
    except GitError as e:
        raise CatchUpError(f"git cannot read {branch} against origin: {str(e)[-200:]}") from e
    if not extra:
        return ""
    if foreign:
        raise CatchUpError(f"origin's {branch} holds commits that are not the orchestrator's notes ({', '.join(foreign)}); "
                           "nothing was changed: hand back and name it, or ask the orchestrator")
    shas = ", ".join(sha[:12] for sha in extra)
    if not ahead:
        code, out = run_git(repo, ["merge", "-q", "--ff-only", "FETCH_HEAD"])
        if code != 0:
            raise CatchUpError(f"the fast-forward to the orchestrator's notes failed: {out.strip()[-200:]}")
        return f"Your branch took in the orchestrator's note commit(s) {shas} (a fast-forward)."
    code, out = run_git(repo, ["rebase", "-q", "FETCH_HEAD"])
    if code != 0:
        run_git(repo, ["rebase", "--abort"])
        raise CatchUpError(f"your commits could not be replayed on the orchestrator's notes: {out.strip()[-200:]}; "
                           "nothing was changed")
    return (f"Your branch took in the orchestrator's note commit(s) {shas} and replayed your {len(ahead)} commit(s) "
            "on top of them.")


def expected_after(repo: str, ticket: Any, expected: str) -> str:
    """The commit a child's step_done expects, after the moves the harness made itself on its branch, in time order:
    its handback and question commits (each from its parent; live run 6) and the catch-ups of the orchestrator's notes
    (MOVES). A commit nobody of these made is no move: step_done still refuses it.

    Args:
        repo: the child's clone.
        ticket: the child's ticket.
        expected: the plan's last commit (or its base).

    Returns:
        The commit the branch may stand on now.
    """
    ticket = ticket or {}
    moves = [(int(m.get("at") or 0), m.get("from"), m.get("to")) for m in ticket.get(MOVES) or []]
    made = [ticket.get("handback") or {}] + [a for a in ticket.get("asks") or [] if isinstance(a, dict)]
    for commit in made:
        if commit.get("sha"):
            try:
                moves.append((int(commit.get("at") or 0), git(repo, "rev-parse", f"{commit['sha']}^").strip(),
                              commit["sha"]))
            except GitError:
                continue
    for _, start, end in sorted(moves, key=lambda move: move[0]):
        expected = end if start == expected and end else expected
    return expected
