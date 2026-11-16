"""Review: the parent's side of a handed-back child (docs/05b-orchestra-cloud.md part 3). The parent reads no code:
it fetches the child's branch, reads the receipt, reruns the tests itself, then accepts (one pull request into the
unit's base; nothing is merged here) or sends the child back (at most 3 rounds).

The child's machine and ledger are not the parent's: every fact comes from the branch. Messages to a child are sent
by the parent's model with send_message; the answers here say exactly what to send."""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from harness.utils.git.facts import top
from harness.utils.git.github import GitHubError, repo_of
from harness.utils.git.run import git
from harness.utils.orchestra import crew
from harness.utils.orchestra.brief import branch
from harness.utils.orchestra.card import card_of, unit_spec
from harness.utils.orchestra.fetch import checkout, rerun
from harness.utils.orchestra.work import RECEIPTS, find_receipt
from harness.utils.plan import tickets
from harness.utils.shapes import Card, CrewEntry, PlanStore, Ticket

if TYPE_CHECKING:
    from harness.utils.ledger.recorder import Recorder

ROUNDS = 3
CHECKED = "checked"
TAIL = 1500


class ReviewError(ValueError):
    """The parent's review refuses; the message says why and what to do."""


def now() -> int:
    """The time now in ms.

    Returns:
        Milliseconds since the epoch.
    """
    return int(time.time() * 1000)


def child_of(port: PlanStore, sid: str, name: str, live: bool = True) -> tuple[Ticket, Card, CrewEntry]:
    """The parent's ticket, the child's card and its crew entry.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        live: True when the child must not have ended (accepted, forgotten, released, removed).

    Returns:
        (ticket, card, entry).

    Raises:
        ReviewError: no delegated plan in force, no such child, not started, or ended when live.
    """
    ticket = port.ticket(sid)
    plan = crew.delegated(ticket)
    if plan is None:
        raise ReviewError("no delegated plan is in force in this session")
    card = card_of(plan, name)
    if card is None:
        raise ReviewError(f"{name} is no child of plan {plan['id']}")
    entry = (ticket.get("crew") or {}).get(name)
    if not entry:
        raise ReviewError(f"{name} has not started: spawn it first")
    if live and entry.get("state") in crew.ENDED:
        raise ReviewError(f"{name} has ended ({entry['state']})")
    return ticket, card, entry


def set_entry(port: PlanStore, sid: str, name: str, card: Card, change: dict[str, Any], state: str) -> CrewEntry:
    """Change a child's crew entry and append its story row, in one transaction.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        card: its card.
        change: the entry's keys to set.
        state: the state of the story row (accepted, rejected, checked...).

    Returns:
        The entry written.
    """
    def write(con: sqlite3.Connection, rec: Recorder) -> CrewEntry:
        fresh = tickets.latest(con, sid)
        entry = {**fresh["crew"][name], **change}
        crew.story(con, fresh["plan"]["id"], card, state, entry.get("backs", 0), entry.get("sid", ""),
                   entry.get("model", ""))
        tickets.save(con, {**fresh, "crew": {**fresh["crew"], name: entry}})
        return entry
    return port.write(write)


def covered(receipt: dict[str, Any], card: Card) -> list[int]:
    """The criteria of the card without an active behaviour whose description starts "AC<n>" and that names a test.

    Args:
        receipt: the child's receipt.
        card: its card.

    Returns:
        The missing criteria's numbers (from 1).
    """
    found = set()
    for entry in (receipt.get("behaviours") or {}).values():
        m = re.match(r"^\s*AC\s*(\d+)\s*[:.)-]", str(entry.get("what", "")), re.I)
        if m and entry.get("status") == "active" and entry.get("tests"):
            found.add(int(m.group(1)))
    return [n for n in range(1, len(card.get("ac", [])) + 1) if n not in found]


def check(port: PlanStore, sid: str, name: str, units: dict[str, Any], verify: list[str], timeout_min: int = 10) -> str:
    """Check a handed-back child: its receipt on its branch, the coverage of its criteria, and a rerun of its tests.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        units: the declared units by name.
        verify: the config's test command (the home's, for a home child).
        timeout_min: the minutes each test run may take (1 to 30).

    Returns:
        The result: green, or what is missing or red.

    Raises:
        ReviewError: a bad timeout, no such child, no repository, no receipt, a stale or untrustworthy receipt.
    """
    if not 1 <= int(timeout_min) <= 30:
        raise ReviewError("timeoutMin is 1 to 30")
    ticket, card, entry = child_of(port, sid, name)
    repo, unit = top(ticket["plan"]["root"]), unit_spec(card, units)
    if not repo:
        raise ReviewError("the plan's root is in no git repository")
    command = [sys.executable if w == "{python}" else w for w in (unit.get("verify") or verify)]
    if not command:
        raise ReviewError("the unit has no test command: declare verify for it in the config's units")
    ref = branch(ticket["plan"]["id"], name)
    with checkout(unit, repo, ref) as folder:
        receipt = find_receipt(folder, name)
        if receipt is None:
            raise ReviewError(f"{ref} holds no receipt: {name} has not handed back")
        tip = [f for f in git(folder, "show", "--name-only", "--format=", "HEAD").splitlines() if f.strip()]
        if tip != [f"{RECEIPTS}/{name}.json"]:
            raise ReviewError(f"the tip of {ref} is not its receipt: the receipt does not describe the code after it")
        if receipt.get("parent") != sid or receipt.get("name") != name:
            raise ReviewError(f"the receipt on {ref} is not of {name} of this session")
        if entry.get("sentBackAt") and int(receipt.get("at", 0)) <= int(entry["sentBackAt"]):
            raise ReviewError(f"{name} has not handed back since it was sent back")
        missing, dirty = covered(receipt, card), list(receipt.get("uncommitted") or [])
        root = folder if unit.get("path", ".") in ("", ".") else str(Path(folder) / unit["path"])
        tests = sorted({t for b in (receipt.get("behaviours") or {}).values() for t in b.get("tests", [])})
        ok, tail = rerun(root, command, tests, int(timeout_min) * 60)
    green = ok and not missing and not dirty and receipt.get("verify") == "ok"
    lines = [f"AC {len(card['ac']) - len(missing)} of {len(card['ac'])} covered by a registered behaviour; the tests "
             f"run again in the {unit.get('path', '.')} folder of {ref}: {'green' if ok else 'RED'}."]
    lines += [f"missing: AC{n}" for n in missing] + [f"uncommitted at handback: {f}" for f in dirty]
    lines += [] if receipt.get("verify") == "ok" else [f"the child's own verify was {receipt.get('verify')}"]
    lines += [f"refused (nobody could answer): {r}" for r in receipt.get("refused", [])]
    if not ok:
        lines.append(tail[-TAIL:])
    set_entry(port, sid, name, card, {"state": crew.HANDED_BACK, "checkedAt": entry.get("backs", 0) if green else None,
                                      "lastCheck": {"green": green, "at": now(), "lines": lines[:12]},
                                      "receipt": receipt}, CHECKED)
    head = "Green: accept it with run('orchestra', 'accept', {name})." if green else \
        "Not green: send it back with run('orchestra', 'reject', {name, why})."
    return "\n".join([f"Check of {name}: {head}"] + lines)


def accept(port: PlanStore, sid: str, name: str, units: dict[str, Any], github: Callable[..., Any]) -> str:
    """Accept a child whose check is green this round: open one pull request from its branch into its unit's base.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        units: the declared units by name.
        github: call(method, path, fields) -> the JSON answer (utils/git/github.call).

    Returns:
        The pull request's number and URL, and what comes next. A child sent back after a first accept keeps its pull
        request: its branch's new commits are in it already.

    Raises:
        ReviewError: no green check this round, the unit is not on GitHub, or GitHub refuses.
    """
    ticket, card, entry = child_of(port, sid, name)
    if entry.get("checkedAt") is None or entry.get("checkedAt") != entry.get("backs", 0):
        raise ReviewError(f"{name} has not passed a check this round: run('orchestra', 'check', {{name}}) first")
    unit = unit_spec(card, units)
    repo = top(ticket["plan"]["root"])
    url = unit.get("repo") or (git(repo, "config", "--get", "remote.origin.url").strip() if repo else "")
    ref = branch(ticket["plan"]["id"], name)
    body = "\n".join([f"Child {name} of the delegated plan {ticket['plan']['id']} ({ticket['draft']}).", "",
                      "Acceptance criteria, each with a registered test the parent ran again:"]
                     + [f"- AC{n}: {a}" for n, a in enumerate(card["ac"], 1)]
                     + ["", f"The receipt is {RECEIPTS}/{name}.json on {ref}."])
    held = entry.get("pr") or {}
    try:
        pr = {"number": held["number"], "html_url": held.get("url")} if held.get("number") else github(
            "POST", f"repos/{repo_of(url)}/pulls", {"head": ref, "base": unit.get("base", "main"),
                                                    "title": f"{name}: {card['goal']}"[:200], "body": body})
    except GitHubError as e:
        raise ReviewError(f"the pull request was not opened: {e}") from e
    set_entry(port, sid, name, card, {"state": crew.ACCEPTED, "pr": {"number": pr.get("number"),
              "url": pr.get("html_url"), "repo": repo_of(url), "base": unit.get("base", "main")}}, crew.ACCEPTED)
    kept = drop_receipt(github, repo_of(url), ref, name)
    return (f"{name} accepted: pull request #{pr.get('number')} ({pr.get('html_url')}) from {ref} into "
            f"{unit.get('base', 'main')}. {kept} Nothing is merged yet: when every child is accepted, run('orchestra', "
            "'land', {}) merges the pull requests.")


def drop_receipt(github: Callable[..., Any], repo: str, ref: str, name: str) -> str:
    """Take the receipt off the child's branch through GitHub, so the merge does not carry it into the base; the
    parent's ledger keeps it (the crew entry's receipt, from check).

    Args:
        github: call(method, path, fields) -> the JSON answer.
        repo: owner/name of the unit's repository.
        ref: the child's branch.
        name: the child's name.

    Returns:
        A sentence for the answer: taken off, or why not (then it lands with the merge).
    """
    path = f"repos/{repo}/contents/{RECEIPTS}/{name}.json"
    try:
        sha = github("GET", f"{path}?ref={ref}").get("sha")
        github("DELETE", path, {"message": f"Keep the receipt of {name} out of the base", "sha": str(sha),
                                "branch": ref})
    except (GitHubError, AttributeError) as e:
        return f"The receipt stays on the branch ({e}); it lands with the merge."
    return "Its receipt is kept in the ledger and taken off the branch."


def reject(port: PlanStore, sid: str, name: str, why: str) -> str:
    """Send a child back with a reason: one round, at most ROUNDS.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        why: the reason, for the child.

    Returns:
        The round and the exact send_message to make.

    Raises:
        ReviewError: no such child, ended (an accepted child whose pull request is not merged may still be sent back,
            for a conflict), no reason, or ROUNDS rounds already (the user decides then).
    """
    text = " ".join(str(why).split())
    if not text:
        raise ReviewError("say why the child is sent back")
    _, card, entry = child_of(port, sid, name, live=False)
    if entry.get("state") in crew.ENDED and (entry.get("state") != crew.ACCEPTED or entry.get("merged")):
        raise ReviewError(f"{name} has ended ({entry['state']}{', merged' if entry.get('merged') else ''})")
    if entry.get("backs", 0) >= ROUNDS:
        raise ReviewError(f"{name} was sent back {ROUNDS} times: the user decides now (forget it, or say what to do)")
    n = entry.get("backs", 0) + 1
    sent = list(entry.get("sent", [])) + [{"at": now(), "how": "send-back", "text": text[:1000]}]
    set_entry(port, sid, name, card, {"state": crew.RUNNING, "backs": n, "sentBackAt": now(), "checkedAt": None,
                                      "sent": sent}, "rejected")
    return (f"{name} sent back (round {n} of {ROUNDS}). Send it now with send_message to {entry['sid']}: "
            f"\"Send-back from the orchestrator, round {n} of {ROUNDS}: {text} Fix it on your branch, verify, push, "
            "and hand back again.\" Check it again after its next handback.")


def answer(port: PlanStore, sid: str, name: str, text: str) -> str:
    """The parent's reply to a child's question, kept on its crew entry.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        text: the reply.

    Returns:
        The exact send_message to make.

    Raises:
        ReviewError: no such child, ended, or an empty reply.
    """
    reply = " ".join(str(text).split())
    if not reply:
        raise ReviewError("the answer is empty")
    _, card, entry = child_of(port, sid, name)
    sent = list(entry.get("sent", [])) + [{"at": now(), "how": "answer", "text": reply[:1000]}]
    set_entry(port, sid, name, card, {"sent": sent}, "answered")
    return f"Send it now with send_message to {entry['sid']}: \"Answer from the orchestrator: {reply}\""


def forget(port: PlanStore, sid: str, name: str, why: str) -> str:
    """Drop a child that will not come back; its name may be spawned again.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        why: the reason.

    Returns:
        What was done, and that its session stays until the user agrees to archive it.

    Raises:
        ReviewError: no such child, or ended.
    """
    _, card, entry = child_of(port, sid, name)
    set_entry(port, sid, name, card, {"state": crew.FORGOTTEN, "forgotWhy": " ".join(str(why).split())[:300]},
              crew.FORGOTTEN)
    return (f"{name} forgotten; spawn it again to give its card to a new child. Its session {entry['sid']} stays "
            "until the user agrees to archive it.")


def read(port: PlanStore, sid: str, name: str, units: dict[str, Any]) -> str:
    """The receipt of a child, read from its branch.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        units: the declared units by name.

    Returns:
        The receipt as JSON text, or that there is none yet.

    Raises:
        ReviewError: no such child, or its branch cannot be fetched.
    """
    ticket, card, _ = child_of(port, sid, name, live=False)
    repo = top(ticket["plan"]["root"])
    with checkout(unit_spec(card, units), repo, branch(ticket["plan"]["id"], name)) as folder:
        receipt = find_receipt(folder, name)
    return json.dumps(receipt, ensure_ascii=False, indent=1) if receipt else f"{name} has no receipt yet."

