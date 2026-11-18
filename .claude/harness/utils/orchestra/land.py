"""Land: the final route of a delegated plan (docs/05b-orchestra-cloud.md part 3, the user's flow of 2026-11-16).
When every child has ended (accepted, forgotten or released), the parent merges the accepted children's pull
requests one by one, in the plan's order. A conflict stops it: the answer names the pull request and its files, and
the parent resolves it (or sends the child back) and lands again. After the last merge each unit's tests run on its
merged base; green, with nothing of the parent's own left, closes the delegated plan as delivered. When the parent
locked acceptance tests (utils/orchestra/locked.py), the children merge into the plan branch, the tests run there, and
one pull request takes the plan branch into the base: the plan is delivered only after the user merged it."""
from __future__ import annotations

import fnmatch
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

from harness.utils.contracts import now
from harness.utils.git.facts import top
from harness.utils.git.github import GitHubError
from harness.utils.git.run import GitError, git, run_git
from harness.utils.ledger import store
from harness.utils.orchestra import crew, locked, synced
from harness.utils.orchestra.brief import branch
from harness.utils.orchestra.card import unit_spec
from harness.utils.orchestra.fetch import checkout, rerun, same_repo
from harness.utils.orchestra.review import ReviewError, set_entry
from harness.utils.shapes import Card, PlanStore, Ticket

MERGED = "merged"
TRIES, WAIT = 10, 3  # how often and how long apart land asks GitHub whether a pull request can merge


def covers(card: Card, path: str) -> bool:
    """Whether a card covers a file: one of its change or test paths is it, a folder (ending in /) holding it, or a
    pattern matching it.

    Args:
        card: a child's card.
        path: a file of the plan.

    Returns:
        True when the child's work covers the file.
    """
    for p in list(card.get("change", [])) + list(card.get("tests", [])):
        if p == path or (p.endswith("/") and path.startswith(p)) or fnmatch.fnmatch(path, p):
            return True
    return False


def own_files(ticket: Ticket) -> list[str]:
    """The files of the delegated plan no card covers: the parent's own work.

    Args:
        ticket: the parent's ticket.

    Returns:
        Those files, in the plan's order.
    """
    plan, cards = ticket["plan"], ticket["plan"].get("children", [])
    return [f for f in plan.get("files", []) if not any(covers(c, f) for c in cards)]


def conflicts(repo: str, base: str, ref: str) -> list[str]:
    """The files a merge of ref into base would conflict on, read locally (git merge-tree, git 2.38 or newer); [] when
    it merges cleanly here or git cannot tell.

    Args:
        repo: the parent's repository root.
        base: the base branch.
        ref: the child's branch.

    Returns:
        The conflicted files, 20 at most.
    """
    try:
        git(repo, "fetch", "-q", "origin", base, ref, timeout=300)
    except GitError:
        return []
    code, out = run_git(repo, ["merge-tree", "--write-tree", "--name-only", "--no-messages", f"origin/{base}",
                               f"origin/{ref}"])
    if code != 1:
        return []
    return [line.strip() for line in out.splitlines()[1:] if line.strip()][:20]


def merges_cleanly(repo: str, base: str, ref: str) -> bool:
    """Whether ref merges into base without a conflict, tried locally (git merge-tree).

    Args:
        repo: the parent's repository root.
        base: the base branch.
        ref: the child's branch.

    Returns:
        True when the merge is clean here; False on a conflict or when git cannot tell.
    """
    try:
        git(repo, "fetch", "-q", "origin", base, ref, timeout=300)
        git(repo, "merge-tree", "--write-tree", "--name-only", "--no-messages", f"origin/{base}", f"origin/{ref}")
        return True
    except GitError:
        return False


def merge_one(github: Callable[..., Any], name: str, pr: dict[str, Any]) -> str:
    """Merge one pull request, or find it merged already.

    Args:
        github: call(method, path, fields) -> the JSON answer.
        name: the child's name.
        pr: its pull request {number, url, repo, base}.

    Returns:
        The merge commit's sha.

    Raises:
        GitHubError: GitHub refuses (a conflict, a check, a protection).
    """
    path = f"repos/{pr['repo']}/pulls/{pr['number']}"
    for _ in range(TRIES):  # right after a push GitHub has not decided yet (mergeable null)
        seen = github("GET", path)
        if seen.get("merged"):
            return str(seen.get("merge_commit_sha") or "")
        if seen.get("mergeable") is not None:
            break
        time.sleep(WAIT)
    done = github("PUT", f"{path}/merge", {"merge_method": "merge",
                                          "commit_title": f"Merge {name} (pull request #{pr['number']})"})
    return str(done.get("sha") or "")


def conflict_text(name: str, pr: dict[str, Any], ref: str, files: list[str], why: str) -> str:
    """What the parent does when a pull request does not merge.

    Args:
        name: the child's name.
        pr: its pull request.
        ref: its branch.
        files: the conflicted files, when known.
        why: GitHub's words.

    Returns:
        The two ways on: resolve it here, or send the child back.
    """
    base = pr.get("base", "main")
    where = f" Conflicts in: {', '.join(files)}." if files else ""
    return (f"Pull request #{pr['number']} of {name} does not merge into {base} ({why[-300:]}).{where}\n"
            f"Resolve it here, as the parent: fetch, stand on {ref}, merge origin/{base} into it, fix those files "
            f"(they are files of the delegated plan), verify, commit with run('git', 'commit', {{files, message}}), "
            f"push {ref} with run('git', 'run', {{repo, args: ['push', 'origin', '{ref}']}}), then run('orchestra', "
            f"'land', {{}}) again.\nOr send the child back: run('orchestra', 'reject', {{name: '{name}', why: "
            f"'your branch conflicts with {base}: merge {base} into it, fix, verify, hand back'}}), then check and "
            "accept it again (its pull request stays the same).")


def land(port: PlanStore, sid: str, units: dict[str, Any], verify: list[str], github: Callable[..., Any],
         timeout_min: int = 10, folder: str = "") -> str:
    """The final route: merge every accepted child's pull request, run each unit's tests on its merged base, and
    close the delegated plan as delivered when all is green and nothing of the parent's own is left.

    Args:
        port: the ledger port.
        sid: the parent's session.
        units: the declared units by name.
        verify: the config's test command (the home's).
        github: call(method, path, fields) -> the JSON answer (utils/git/github.call).
        timeout_min: the minutes each unit's test run may take (1 to 30).
        folder: the store's Drive folder; when set, the plan is delivered only when every child that ended has its
            database in the store (utils/orchestra/synced.py) or the user waived it.

    Returns:
        What was merged, and the plan's state: delivered, waiting for the parent's own files or for the children's
        databases, a conflict, or red.

    Raises:
        ReviewError: no delegated plan, a child that has not ended, or nothing accepted.
    """
    ticket = port.ticket(sid)
    plan = crew.delegated(ticket)
    if plan is None:
        raise ReviewError("no delegated plan is in force in this session")
    team = ticket.get("crew") or {}
    open_ones = [c["name"] for c in plan["children"] if team.get(c["name"], {}).get("state") not in crew.ENDED]
    if open_ones:
        raise ReviewError(f"these children have not ended: {', '.join(open_ones)}; accept or forget each first")
    accepted = [c for c in plan["children"] if team[c["name"]].get("state") == crew.ACCEPTED]
    if not accepted:
        raise ReviewError("no child was accepted: there is nothing to merge")
    repo, lines = top(plan["root"]), []
    for card in accepted:
        entry = team[card["name"]]
        if entry.get(MERGED):
            continue
        pr, ref = entry["pr"], branch(plan["id"], card["name"])
        try:
            sha = merge_one(github, card["name"], pr)
        except GitHubError as e:
            files = conflicts(repo, pr.get("base", "main"), ref) if repo and same_repo(unit_spec(card, units), repo) \
                else []
            clean = not files and repo and same_repo(unit_spec(card, units), repo) and merges_cleanly(
                repo, pr.get("base", "main"), ref)
            if clean:
                return "\n".join(lines + [f"Pull request #{pr['number']} of {card['name']} merges cleanly here, but "
                                           f"GitHub refused it ({str(e)[-200:]}): it may not have finished checking it. "
                                           "Run('orchestra', 'land', {}) again in a minute."])
            return "\n".join(lines + [conflict_text(card["name"], pr, ref, files, str(e))])
        set_entry(port, sid, card["name"], card, {MERGED: {"sha": sha, "at": now()}}, MERGED)
        lines.append(f"Merged #{pr['number']} of {card['name']} into {pr.get('base', 'main')} ({sha[:12]}).")
    red, held = [], (ticket.get(locked.LOCK) or {}).get("branch", "")  # with a lock, the children merged into it
    for spec in {json.dumps(unit_spec(c, units), sort_keys=True): unit_spec(c, units) for c in accepted}.values():
        command = [sys.executable if w == "{python}" else w for w in (spec.get("verify") or verify)]
        if not command:
            continue
        target = held or spec.get("base", "main")
        proofs = [p for c in accepted if unit_spec(c, units) == spec for p in c.get("acTests", [])]  # for a {test} command
        with checkout(spec, repo, target) as tree:
            root = tree if spec.get("path", ".") in ("", ".") else str(Path(tree) / spec["path"])
            ok, tail = rerun(root, command, proofs, int(timeout_min) * 60)
        lines.append(f"The tests of {spec.get('repo') or 'the home'} ({spec.get('path', '.')}) on the merged "
                     f"{target}: {'green' if ok else 'RED'}.")
        if not ok:
            red.append(tail[-1500:])
    if red:
        return "\n".join(lines + ["Not delivered: a merged base is red. Fix it through a new plan, then land again."]
                         + red)
    if held:  # the plan branch goes into the base only by the user's word
        try:
            more, merged = locked.plan_prs(port, sid, github)
        except locked.LockError as e:
            return "\n".join(lines + [str(e)])
        lines += more
        if not merged:
            return "\n".join(lines)
    own = own_files(port.ticket(sid))
    if own and port.ticket(sid).get("phase") != "deliver":
        return "\n".join(lines + [f"Every pull request is merged. The plan waits for your own files ({', '.join(own)}): "
                                  "commit them with step_done, then run('orchestra', 'land', {}) again."])
    gaps = synced.missing(port, port.ticket(sid)) if folder else []
    if gaps:
        db = store.place(port, "db") if folder == store.folder() else ""
        return "\n".join(lines + ["Every pull request is merged and green. " + synced.ask_text(port.ticket(sid), folder,
                                                                                            gaps, db)])
    port.close_plan(sid, port.ticket(sid), "delivered", lines)
    return "\n".join(lines + [f"Plan {plan['id']} ({ticket['draft']}) is delivered. Delete the check-in if you set one "
                              "(delete_trigger). Then run('orchestra', 'remove', {}) for the child sessions, and report "
                              "to the user; the merged branches are left for the user to delete."]
                     + ([f"Save your own ledger too: run('ledger', 'export', {{reason: 'plan-close'}}) and upload it "
                         f"(its name carries orch.{ticket['draft']}.parent)."] if folder else []))
