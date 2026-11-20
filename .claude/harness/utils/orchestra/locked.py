"""Locked: the acceptance tests the parent locks for its children (docs/system.md sections 5 and 6). There is no plan
branch: the parent writes each card's acTests in its own tree, at their paths from the plan's root; lock keeps the
text and the content hash of each file in the ledger (pl_notes of kind FILE, the hashes in the ticket's lock), pushes
nothing, and deletes the parent's untracked copies (clear): a red test left in its tree would keep its verify red (live
run 2). Each child's start commit adds its tests to its branch (utils/orchestra/draft.py); the child never changes them,
and the parent's check runs its own copy (texts) on the child's merge request. Once a child has started, nothing is
locked again."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from harness.utils.git.facts import top
from harness.utils.git.run import GitError, git
from harness.utils.ledger.recorder import Recorder
from harness.utils.ledger.store import note
from harness.utils.ledger.writes import content_hash
from harness.utils.orchestra import crew
from harness.utils.orchestra.card import unit_spec
from harness.utils.orchestra.fetch import same_repo
from harness.utils.plan import tickets
from harness.utils.shapes import Card, PlanStore, Ticket

LOCK = "lock"  # the ticket's key: {"units": [{repo, path, base, files: {path: hash}}], "at"}
FILE = "lock.file"  # pl_notes of the parent: target = the path as the card names it, key = its hash, text = it


class LockError(ValueError):
    """The acceptance tests cannot be locked; the message says why."""


def in_unit(spec: dict[str, Any], path: str) -> str:
    """The path of a card's file in its unit's repository.

    Args:
        spec: the unit's spec {repo, path, ...}.
        path: the file's path, as the card names it.

    Returns:
        The path from the top of the repository.
    """
    folder = str(spec.get("path") or ".").strip("/")
    return path if folder in ("", ".") else f"{folder}/{path}"


def on_origin(spec: dict[str, Any], repo: str, ref: str) -> bool:
    """Whether a branch is on the unit's origin.

    Args:
        spec: the unit's spec.
        repo: the parent's repository root.
        ref: the branch.

    Returns:
        True when the remote has it.
    """
    remote = "origin" if same_repo(spec, repo) else spec["repo"]
    try:
        return bool(git(repo, "ls-remote", "--heads", remote, ref).strip())
    except GitError:
        return False


def lock(port: PlanStore, sid: str, units: dict[str, Any]) -> str:
    """Lock the acceptance tests of the delegated plan in force: keep the text and hash of each in the ledger, the
    hashes in the ticket. Nothing is pushed and no branch is made: each child's start commit adds its tests.

    Args:
        port: the ledger port.
        sid: the parent's session.
        units: the plan's units by name (card.plan_units).

    Returns:
        What was locked.

    Raises:
        LockError: no delegated plan, no card with acTests, a child has started, or a file is not written.
    """
    ticket = port.ticket(sid)
    plan = crew.delegated(ticket)
    if plan is None:
        raise LockError("no delegated plan is in force in this session")
    cards = [c for c in plan["children"] if c.get("acTests")]
    if not cards:
        raise LockError("no card names acTests: there is nothing to lock")
    if ticket.get("crew"):
        raise LockError("a child has started: its acceptance tests are locked as they were")
    root = Path(plan["root"])
    if not top(plan["root"]):
        raise LockError("the plan's root is in no repository")
    missing = [p for c in cards for p in c["acTests"] if not (root / p).is_file()]
    if missing:
        raise LockError(f"write these acceptance tests first (they are tests of this plan): {', '.join(missing)}")
    groups: dict[str, tuple[dict[str, Any], list[str]]] = {}
    for card in cards:
        spec = unit_spec(card, units)
        key = json.dumps({k: spec.get(k) for k in ("repo", "path", "base")}, sort_keys=True)
        groups.setdefault(key, (spec, []))[1].extend(card["acTests"])
    kept = [{"repo": spec.get("repo") or "", "path": spec.get("path") or ".", "base": spec.get("base", "main"),
             "files": {p: content_hash(str(root / p)) for p in dict.fromkeys(paths)}} for spec, paths in groups.values()]
    texts_now = {p: (root / p).read_text(encoding="utf-8") for unit in kept for p in unit["files"]}

    def write(con: sqlite3.Connection, rec: Recorder) -> None:
        at = int(time.time() * 1000)
        for unit in kept:
            for path, digest in unit["files"].items():
                note(con, FILE, path, digest, texts_now[path], sid, at)
        tickets.save(con, {**tickets.latest(con, sid), LOCK: {"units": kept, "at": at}})
    port.write(write)
    gone, here = clear(root, [p for card in cards for p in card["acTests"]])
    names = ", ".join(texts_now)
    cleared = (f" Your tree keeps no copy of {', '.join(gone)}: the ledger holds it (write it again to lock again)."
               if gone else "") + (f" Kept in your tree, as the repository tracks it: {', '.join(here)}." if here else "")
    return (f"Locked: {names}, their text and hash kept in the ledger; nothing is pushed. Each child's start commit "
            f"adds its tests to its branch; it never changes them, and its check runs your copy.{cleared} Now spawn "
            "the children.")


def clear(root: Path, paths: list[str]) -> tuple[list[str], list[str]]:
    """Delete the parent's copies of the locked tests that its repository does not track: the ledger holds them
    now, and a test that is red until a child writes the code would keep the parent's verify red. A tracked file stays.

    Args:
        root: the plan's root.
        paths: the locked tests, from the root.

    Returns:
        (the paths deleted, the paths kept because they are tracked or cannot be told).
    """
    gone, here = [], []
    for path in dict.fromkeys(paths):
        try:
            tracked = bool(git(str(root), "ls-files", "--", path).strip())
        except GitError:
            tracked = True  # not known: keep it
        if tracked:
            here.append(path)
        else:
            (root / path).unlink(missing_ok=True)
            gone.append(path)
    return gone, here


def locked_files(ticket: Optional[Ticket]) -> dict[str, str]:
    """The files the parent locked, with their content hashes.

    Args:
        ticket: the parent's ticket.

    Returns:
        {path as the cards name it: hash}; {} when nothing is locked.
    """
    held = (ticket or {}).get(LOCK) or {}
    return {p: h for unit in held.get("units", []) for p, h in unit.get("files", {}).items()}


def texts(port: PlanStore, ticket: Optional[Ticket]) -> dict[str, str]:
    """The text of each locked file, from the ledger: the parent's own copy, which the check runs.

    Args:
        port: the ledger port.
        ticket: the parent's ticket (its lock and session).

    Returns:
        {path as the cards name it: text}; a file whose locked hash has no text is left out.
    """
    held, out = locked_files(ticket), {}
    for path, digest in held.items():
        rows = port.rows("SELECT text FROM pl_notes WHERE kind = ? AND target = ? AND key = ? AND sid = ? ORDER BY at "
                         "DESC, rowid DESC LIMIT 1", (FILE, path, digest, (ticket or {}).get("sid")))
        if rows:
            out[path] = rows[0]["text"]
    return out


def changed(folder: str, ticket: Optional[Ticket], card: Card) -> list[str]:
    """The locked files of a card whose content on a checkout of the child's branch is not what was locked: its
    acceptance tests.

    Args:
        folder: the unit's folder in the checkout.
        ticket: the parent's ticket (its lock).
        card: the child's card.

    Returns:
        Its acTests that differ from their locked hash, are gone, or were never locked.
    """
    held = locked_files(ticket)
    return [p for p in card.get("acTests", []) if not held.get(p) or content_hash(str(Path(folder) / p)) != held[p]]


def unlocked(ticket: Optional[Ticket], card: Card) -> list[str]:
    """The acceptance tests of a card that are not locked yet.

    Args:
        ticket: the parent's ticket.
        card: the child's card.

    Returns:
        Its acTests the lock does not hold.
    """
    held = locked_files(ticket)
    return [p for p in card.get("acTests", []) if p not in held]
