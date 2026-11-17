"""Review: the parent's side of a handed-back child (docs/05b-orchestra-cloud.md part 3). The parent reads no code:
it fetches the child's branch, reads the receipt, reruns the tests itself, then accepts (one pull request into the
unit's base; nothing is merged here) or sends the child back (the config's limits.rounds at most).

The child's machine and ledger are not the parent's: every fact comes from the branch. Parent and child talk only
through the branch: a send-back or an answer is a note pushed there (.harness/notes/<name>/), read by a fresh session
of the child that spawn opens; no message is sent (a cloud child cannot answer one)."""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from harness.utils.contracts import now
from harness.utils.git.facts import top
from harness.utils.git.github import GitHubError, repo_of
from harness.utils.git.run import GitError, git
from harness.utils.orchestra import crew
from harness.utils.orchestra.brief import NOTES, branch
from harness.utils.orchestra.card import card_of, unit_spec
from harness.utils.orchestra.fetch import TAIL, FetchError, checkout, drop_receipt, put_note, rerun
from harness.utils.orchestra.work import RECEIPTS, find_receipt
from harness.utils.plan import tickets
from harness.utils.shapes import Card, CrewEntry, PlanStore, Ticket

if TYPE_CHECKING:
    from harness.utils.ledger.recorder import Recorder

CHECKED = "checked"


class ReviewError(ValueError):
    """The parent's review refuses; the message says why and what to do."""


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


def asked_at_tip(folder: str, name: str, tip: list[str]) -> str:
    """The child's question when the tip commit of its branch is a question note (it asked and stopped).

    Args:
        folder: the checkout of the child's branch.
        name: the child's name.
        tip: the files of the tip commit.

    Returns:
        "(question n) <text>", or "" when the tip is no question note.
    """
    if len(tip) != 1 or not re.fullmatch(rf"{re.escape(NOTES)}/{re.escape(name)}/question-(\d+)\.md", tip[0]):
        return ""
    lines = (Path(folder) / tip[0]).read_text(encoding="utf-8").splitlines()
    text = " ".join(l.strip() for l in lines[1:] if l.strip())
    return f"({tip[0].rsplit('-', 1)[1][:-3]}) {text}"


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
        tip = [f for f in git(folder, "show", "--name-only", "--format=", "HEAD").splitlines() if f.strip()]
        asked = asked_at_tip(folder, name, tip)
        if asked:
            raise ReviewError(f"{name} asked a question and stopped: {asked} Answer it with run('orchestra', 'answer', "
                              "{name, text}); a fresh session goes on from the answer.")
        receipt = find_receipt(folder, name)
        if receipt is None:
            raise ReviewError(f"{ref} holds no receipt: {name} has not handed back (it is still working)")
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
    kept = drop_receipt(unit, repo, ref, name)
    return (f"{name} accepted: pull request #{pr.get('number')} ({pr.get('html_url')}) from {ref} into "
            f"{unit.get('base', 'main')}. {kept} Nothing is merged yet: when every child is accepted, run('orchestra', "
            "'land', {}) merges the pull requests.")


def fresh_session(port: PlanStore, sid: str, name: str, card: Card, change: dict[str, Any], state: str, rel: str,
                  sha: str, ref: str) -> str:
    """Keep a note on the child's entry and say how its fresh session is opened.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        card: its card.
        change: the entry's other keys to set.
        state: the story row's state.
        rel: the note's path.
        sha: the note's commit.
        ref: the child's branch.

    Returns:
        The sentence for the answer.
    """
    set_entry(port, sid, name, card, {**change, "fresh": {"note": rel, "at": now(), "sha": sha}}, state)
    return (f"The note is {rel} on {ref} ({sha[:12]}); nothing is sent to the child. Open a fresh session for it now: "
            f"run('orchestra', 'spawn', {{name: '{name}'}}) gives the create_session call (it reads the note first), "
            f"then run('orchestra', 'started', {{name: '{name}', sid}}).")


def reject(port: PlanStore, sid: str, name: str, why: str, units: dict[str, Any], rounds: int) -> str:
    """Send a child back with a reason, one round of at most rounds: a send-back note pushed on its branch, for a fresh
    session of the child.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        why: the reason, for the child.
        units: the declared units by name.
        rounds: the send-backs a child may have (the config's limits.rounds).

    Returns:
        The round, the note, and how to open the fresh session.

    Raises:
        ReviewError: no such child, ended (an accepted child whose pull request is not merged may still be sent back,
            for a conflict), no reason, rounds send-backs already (the user decides then), or the note cannot be pushed.
    """
    text = " ".join(str(why).split())
    if not text:
        raise ReviewError("say why the child is sent back")
    ticket, card, entry = child_of(port, sid, name, live=False)
    if entry.get("state") in crew.ENDED and (entry.get("state") != crew.ACCEPTED or entry.get("merged")):
        raise ReviewError(f"{name} has ended ({entry['state']}{', merged' if entry.get('merged') else ''})")
    if entry.get("backs", 0) >= rounds:
        raise ReviewError(f"{name} was sent back {rounds} times: the user decides now (forget it, or say what to do)")
    n = entry.get("backs", 0) + 1
    ref, rel = branch(ticket["plan"]["id"], name), f"{NOTES}/{name}/sendback-{n}.md"
    note = (f"# Send-back {n} of {rounds} from the orchestrator\n\n{text}\n\nFix it on this branch, verify, push, "
            "and hand back again.\n")
    sha = put_note(unit_spec(card, units), top(ticket["plan"]["root"]) or "", ref, rel, note,
                   f"Send-back {n} of {name}")
    sent = list(entry.get("sent", [])) + [{"at": now(), "how": "send-back", "text": text[:1000], "note": rel}]
    told = fresh_session(port, sid, name, card, {"state": crew.RUNNING, "backs": n, "sentBackAt": now(),
                                                 "checkedAt": None, "sent": sent}, "rejected", rel, sha, ref)
    return f"{name} sent back (round {n} of {rounds}). {told} Check it again after its next handback."


def answer(port: PlanStore, sid: str, name: str, text: str, units: dict[str, Any]) -> str:
    """The parent's reply to a child's question: an answer note pushed on its branch, for a fresh session of the child.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        text: the reply.
        units: the declared units by name.

    Returns:
        The note, and how to open the fresh session.

    Raises:
        ReviewError: no such child, ended, an empty reply, or the note cannot be pushed.
    """
    reply = " ".join(str(text).split())
    if not reply:
        raise ReviewError("the answer is empty")
    ticket, card, entry = child_of(port, sid, name)
    k = sum(1 for s in entry.get("sent", []) if s.get("how") == "answer") + 1
    ref, rel = branch(ticket["plan"]["id"], name), f"{NOTES}/{name}/answer-{k}.md"
    sha = put_note(unit_spec(card, units), top(ticket["plan"]["root"]) or "", ref, rel,
                   f"# Answer {k} from the orchestrator\n\n{reply}\n", f"Answer {k} to {name}")
    sent = list(entry.get("sent", [])) + [{"at": now(), "how": "answer", "text": reply[:1000], "note": rel}]
    return f"Answer {k} to {name}. " + fresh_session(port, sid, name, card, {"sent": sent}, "answered", rel, sha, ref)


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

