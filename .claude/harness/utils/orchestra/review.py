"""Review: the parent's side of a handed-back child (docs/05b-orchestra-cloud.md part 3). The parent reads no code:
it reads the child's handback comment on its draft (the receipt), waits for the project's own CI (none: the phase is
skipped), runs its own tests on the branch merged with the newest base, then accepts (utils/orchestra/land.accept
merges it) or sends the child back (the config's limits.rounds at most).

The child's machine and ledger are not the parent's: every fact comes from the branch and the draft. A send-back or an
answer is a comment of the orchestrator on the child's draft (utils/orchestra/talk.py), never a commit on its branch;
the signed order carries the same words to a running child, and a fresh session reads them in its brief."""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from harness.utils.contracts import now
from harness.utils.git.facts import top
from harness.utils.git.github import GitHubError
from harness.utils.git.run import git, run_git
from harness.utils.orchestra import crew, locked, talk
from harness.utils.orchestra.brief import branch
from harness.utils.orchestra.card import card_of, unit_spec
from harness.utils.orchestra.doorbell import ci_state
from harness.utils.orchestra.draft import DRAFTS, ready
from harness.utils.orchestra.fetch import TAIL, checkout, git_or_empty, rerun
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


def last_word(ticket: Ticket, entry: CrewEntry, name: str, github: Callable[..., Any]) -> Optional[dict[str, Any]]:
    """The child's newest question or handback comment on its draft (talk.newest, from the child).

    Args:
        ticket: the parent's ticket.
        entry: the child's crew entry.
        name: the child's name.
        github: call(method, path, fields?) -> the JSON answer.

    Returns:
        Its meta with words, sha and receipt; None when the child has said neither yet.

    Raises:
        ReviewError: the child has no draft, or GitHub cannot be read.
    """
    where = (ticket.get(DRAFTS) or {}).get(name) or entry.get("pr") or {}
    if not where.get("repo") or not where.get("number"):
        raise ReviewError(f"{name} has no draft pull request to read (spawn opens one for every child)")
    try:
        return talk.newest(talk.comments_of(github, where), name, ("question", "handback"))
    except GitHubError as e:
        raise ReviewError(f"the draft #{where['number']} of {name} cannot be read: {str(e)[-200:]}") from e


def gate(port: PlanStore, sid: str, name: str, card: Card, entry: CrewEntry, where: dict[str, Any], said: dict[str, Any],
         github: Callable[..., Any]) -> dict[str, Any]:
    """The pull request at the handback's commit, past the project's own CI (doorbell.ci_state): red is refused with
    the failed checks, running or unknown is waited for, none (no CI) skips the phase. A draft with no CI yet is made
    ready once, so a CI that skips drafts runs.

    Returns the pull request as GitHub gives it. Raises ReviewError: GitHub cannot be read, the head is not the
    handback's commit, or CI is not green or none.
    """
    try:
        pr = github("GET", f"repos/{where['repo']}/pulls/{where['number']}") or {}
        head = str((pr.get("head") or {}).get("sha") or said.get("sha"))
        state, failed = ci_state(github, where["repo"], head)
    except GitHubError as e:
        raise ReviewError(f"the pull request #{where['number']} of {name} cannot be read: {str(e)[-200:]}") from e
    if head != said.get("sha"):
        raise ReviewError(f"the head of #{where['number']} is not its receipt's commit: the receipt does not describe "
                          "the code after it")
    if state == "red":
        raise ReviewError(f"the project CI is red on {head[:12]}: {'; '.join(failed) or 'see the pull request'}. Send "
                          f"it back: run('orchestra', 'reject', {{name: '{name}', why: '<these failures>'}}).")
    if state in ("running", "unknown"):
        raise ReviewError(f"the project CI has not finished on {head[:12]}: wait for its result, then check again")
    if state == "none" and pr.get("draft") and entry.get("readied") != head:
        ready(port.ticket(sid), name, github)
        set_entry(port, sid, name, card, {"readied": head}, CHECKED)
        raise ReviewError(f"#{where['number']} was a draft and shows no CI yet: it is ready now, so a CI that skips "
                          "drafts may start; check again after its result (with no CI, the next check goes on)")
    return pr


def merged_with(folder: str, base: str) -> str:
    """Merge the newest base into the checkout of the child's branch (what the base would get); the base's commit.
    ReviewError when it conflicts (the files are named) or git cannot do it."""
    git(folder, "fetch", "-q", "origin", base, timeout=300)
    base_sha = git(folder, "rev-parse", "FETCH_HEAD").strip()
    code, out = run_git(folder, ["-c", "user.name=harness", "-c", "user.email=harness@localhost", "merge", "-q",
                                 "--no-edit", base_sha])
    if code != 0:
        files = [f for f in git_or_empty(folder, "diff", "--name-only", "--diff-filter=U").split() if f]
        raise ReviewError(f"the branch does not merge with the newest {base}" + (f": conflicts in {', '.join(files)}"
                          if files else f" ({out.strip()[-200:]})") + ". Send it back to merge it and hand back again.")
    return base_sha


def check(port: PlanStore, sid: str, name: str, units: dict[str, Any], verify: list[str], github: Callable[..., Any],
          timeout_min: int = 10) -> str:
    """Check a handed-back child: its handback comment (the receipt) at the head of its pull request, the project's CI
    (gate), then its branch merged with the newest base (merged_with) and the tests run there: for a card with locked
    acceptance tests (acTests) the parent's OWN copy (a changed copy on the branch is named and red), for any other
    card the coverage of its criteria and its registered tests.

    Args: the ledger port, the parent's session, the child's name, the declared units by name, the config's test
    command (the home's, for a home child), the GitHub call, the minutes each test run may take (1 to 30).

    Returns the result: green, or what is missing or red. Raises ReviewError: a bad timeout, no such child, no
    repository, no receipt, a stale receipt, CI not passed, or a branch that does not merge with the base.
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
    ref, said = branch(ticket["plan"]["id"], name), last_word(ticket, entry, name, github)
    if said and said.get("kind") == "question":
        raise ReviewError(f"{name} asked a question and stopped: ({said.get('n')}) {said.get('words')} Answer it with "
                          "run('orchestra', 'answer', {name, text}); a fresh session goes on from the answer.")
    receipt = (said or {}).get("receipt")
    if not receipt:
        raise ReviewError(f"{name} has posted no handback on its draft: it has not handed back (it is still working)")
    if receipt.get("parent") != sid or receipt.get("name") != name:
        raise ReviewError(f"the receipt on {ref} is not of {name} of this session")
    if entry.get("sentBackAt") and int(receipt.get("at", 0)) <= int(entry["sentBackAt"]):
        raise ReviewError(f"{name} has not handed back since it was sent back")
    where = (ticket.get(DRAFTS) or {}).get(name) or entry.get("pr") or {}
    gate(port, sid, name, card, entry, where, said, github)
    into, own = unit.get("base", "main"), locked.texts(port, ticket)  # own: the parent's copy, from the ledger
    with checkout(unit, repo, ref) as folder:
        if said.get("sha") != git(folder, "rev-parse", "HEAD").strip():
            raise ReviewError(f"the tip of {ref} is not its receipt's commit: the receipt does not describe the code "
                              "after it")
        dirty = list(receipt.get("uncommitted") or [])
        root = folder if unit.get("path", ".") in ("", ".") else str(Path(folder) / unit["path"])
        touched = locked.changed(root, ticket, card) if card.get("acTests") else []
        merged_with(folder, into)
        if card.get("acTests"):  # the parent's own copy judges it, whatever the branch holds
            for test in card["acTests"]:
                (Path(root) / test).write_text(own[test], encoding="utf-8")
            missing = []
            ok, tail = rerun(root, command, list(card["acTests"]), int(timeout_min) * 60)
        else:
            missing = covered(receipt, card)
            tests = sorted({t for b in (receipt.get("behaviours") or {}).values() for t in b.get("tests", [])})
            ok, tail = rerun(root, command, tests, int(timeout_min) * 60)
    green = ok and not missing and not dirty and not touched and receipt.get("verify") == "ok"
    place = f"in the {unit.get('path', '.')} folder of {ref} merged with the newest {into}: {'green' if ok else 'RED'}."
    if card.get("acTests"):
        state = "CHANGED on the branch (red; the parent's own copy ran): " + ", ".join(touched) if touched else \
            "unchanged"
        how = "they run alone" if any("{test}" in w for w in command) else "the unit's suite, which holds them, runs"
        lines = [f"The locked acceptance tests are {state}; {how} {place}"]
    else:
        lines = [f"AC {len(card['ac']) - len(missing)} of {len(card['ac'])} covered by a registered behaviour; the "
                 f"tests run again {place}"]
    lines += [f"missing: AC{n}" for n in missing] + [f"uncommitted at handback: {f}" for f in dirty]
    lines += [] if receipt.get("verify") == "ok" else [f"the child's own verify was {receipt.get('verify')}"]
    lines += [f"refused (nobody could answer): {r}" for r in receipt.get("refused", [])]
    if not ok:
        lines.append(tail[-TAIL:])
    set_entry(port, sid, name, card, {"state": crew.HANDED_BACK, "checkedAt": entry.get("backs", 0) if green else None,
                                      "lastCheck": {"green": green, "at": now(), "lines": lines[:12],
                                                    "sha": said.get("sha")},
                                      "receipt": receipt, "handbackUrl": said.get("url")}, CHECKED)
    head = "Green: accept it with run('orchestra', 'accept', {name}): it merges the pull request." if green else \
        "Not green: send it back with run('orchestra', 'reject', {name, why})."
    return "\n".join([f"Check of {name}: {head}"] + lines)


def accept(*args: Any, **kwargs: Any) -> str:
    """Moved to utils/orchestra/land.accept (it merges); kept for its older callers."""
    from harness.utils.orchestra import land
    return land.accept(*args, **kwargs)


def say_back(port: PlanStore, sid: str, name: str, card: Card, kind: str, n: int, words: str, short: str,
             change: dict[str, Any], state: str, github: Callable[..., Any]) -> str:
    """Post the orchestrator's words as one comment on the child's draft (else its pull request; talk.py), keep them on
    its entry (sent, and fresh: what spawn gives a fresh session's brief), and say how that session is opened.

    Args:
        port, sid, name, card: the ledger port, the parent's session, the child and its card.
        kind, n: sendback or answer, and its number.
        words: the comment's words; short: what the entry's sent list keeps.
        change, state: the entry's other keys, and the story row's state.
        github: call(method, path, fields?) -> the JSON answer.

    Returns:
        The sentence for the answer.

    Raises:
        ReviewError: the child has no draft or pull request, or GitHub refuses the comment.
    """
    ticket, _, entry = child_of(port, sid, name, live=False)
    where = (ticket.get(DRAFTS) or {}).get(name) or entry.get("pr") or {}
    if not where.get("repo") or not where.get("number"):
        raise ReviewError(f"{name} has no draft pull request to post on (spawn opens one for every child)")
    try:
        made = talk.post(port, sid, github, where, kind, {"child": name, "plan": ticket["plan"]["id"],
                                                          "from": talk.PARENT, "n": n}, [words])
    except GitHubError as e:
        raise ReviewError(f"the {kind} was not posted on #{where['number']}: {str(e)[-200:]}") from e
    url, what = str(made.get("html_url") or where.get("url") or ""), f"{'send-back' if kind == 'sendback' else kind} {n}"
    sent = list(entry.get("sent", [])) + [{"at": now(), "how": what.split()[0], "text": short[:1000], "comment": url}]
    fresh = {"note": f"{what} ({url}): {words}", "words": words, "url": url, "at": now()}  # crew.status shows note
    set_entry(port, sid, name, card, {**change, "sent": sent, "fresh": fresh}, state)
    return (f"The {what} is the comment {url} on its draft; nothing is sent to the child. Open a fresh session for it "
            f"now: run('orchestra', 'spawn', {{name: '{name}'}}) gives the create_session call (its brief holds the "
            f"words), then run('orchestra', 'started', {{name: '{name}', sid}}).")


def reject(port: PlanStore, sid: str, name: str, why: str, rounds: int, github: Callable[..., Any]) -> str:
    """Send a child back with a reason, one round of at most rounds: a send-back comment on its draft.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        why: the reason, for the child.
        rounds: the send-backs a child may have (the config's limits.rounds).
        github: call(method, path, fields?) -> the JSON answer.

    Returns:
        The round, the comment, and how to open the fresh session.

    Raises:
        ReviewError: no such child, ended (an accepted child whose pull request is not merged may still be sent back,
            for a conflict), no reason, rounds send-backs already (the user decides then), or no comment was posted.
    """
    text = " ".join(str(why).split())
    if not text:
        raise ReviewError("say why the child is sent back")
    _, card, entry = child_of(port, sid, name, live=False)
    if entry.get("state") in crew.ENDED and (entry.get("state") != crew.ACCEPTED or entry.get("merged")):
        raise ReviewError(f"{name} has ended ({entry['state']}{', merged' if entry.get('merged') else ''})")
    if entry.get("backs", 0) >= rounds:
        raise ReviewError(f"{name} was sent back {rounds} times: the user decides now (forget it, or say what to do)")
    n = entry.get("backs", 0) + 1
    words = f"Send-back {n} of {rounds}: {text} Fix it on your branch, verify, push, and hand back again."
    told = say_back(port, sid, name, card, "sendback", n, words, text, {"state": crew.RUNNING, "backs": n,
                    "sentBackAt": now(), "checkedAt": None}, "rejected", github)
    return f"{name} sent back (round {n} of {rounds}). {told} Check it again after its next handback."


def answer(port: PlanStore, sid: str, name: str, text: str, github: Callable[..., Any]) -> str:
    """The parent's reply to a child's question: an answer comment on its draft.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        text: the reply.
        github: call(method, path, fields?) -> the JSON answer.

    Returns:
        The comment, and how to open the fresh session.

    Raises:
        ReviewError: no such child, ended, an empty reply, or no comment was posted.
    """
    reply = " ".join(str(text).split())
    if not reply:
        raise ReviewError("the answer is empty")
    _, card, entry = child_of(port, sid, name)
    k = sum(1 for s in entry.get("sent", []) if s.get("how") == "answer") + 1
    return f"Answer {k} to {name}. " + say_back(port, sid, name, card, "answer", k, reply, reply, {}, "answered", github)


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


def read(port: PlanStore, sid: str, name: str, github: Callable[..., Any]) -> str:
    """The receipt of a child, read from its handback comment on its draft.

    Args:
        port: the ledger port.
        sid: the parent's session.
        name: the child's name.
        github: call(method, path, fields?) -> the JSON answer.

    Returns:
        The receipt as JSON text, or that there is none yet.

    Raises:
        ReviewError: no such child, no draft, or GitHub cannot be read.
    """
    ticket, _, entry = child_of(port, sid, name, live=False)
    said = last_word(ticket, entry, name, github)
    receipt = (said or {}).get("receipt") if (said or {}).get("kind") == "handback" else None
    return json.dumps(receipt, ensure_ascii=False, indent=1) if receipt else f"{name} has no receipt yet."
