"""Synced: a delegated plan is done only when every child that ended has its database in the store (the user's rule of
2026-11-16; docs/05b-orchestra-cloud.md). Harness code cannot call Google Drive; the hook can read Drive's own answer.
So the parent's model searches the store folder, and seen() reads the answer of that search (not the model's words):
each file named as a copy of this plan's run, "<session>__...__orch.<plan id>.<child>__...db", is kept on that child's
crew entry when its session is the child's: its cloud session id, or its own id inside its harness, which its receipt
names (the two differ in the cloud). A copy older than the child's handback does not count.

missing() names who is not synced yet; a child whose session is gone and can never upload passes only with the user's
"Allow" in the form waiver_question() gives (waiver_accepts keeps it, per plan and child)."""
from __future__ import annotations

import calendar
import hashlib
import json
import re
import sqlite3
import time
from typing import TYPE_CHECKING, Any, Iterator, Optional

from harness.utils.ledger.store import session_part
from harness.utils.plan import tickets
from harness.utils.shapes import PlanStore, Ticket

if TYPE_CHECKING:
    from harness.utils.ledger.recorder import Recorder

COPY = re.compile(r"^(?P<session>[A-Za-z0-9-]+)__[0-9a-f]{6}-(?P<seq>\d{3})__(?P<stamp>\d{8}T\d{6}Z)__[a-z-]+__"
                  r"orch\.(?P<draft>pd-[a-z0-9-]+)\.(?P<name>[a-z0-9][a-z0-9-]*)__[0-9a-z]+__s[0-9a-f]{8}\.db(?:\.gz)?$")
WAIVER = re.compile(r"^Close plan (?P<draft>pd-[a-z0-9-]+) without the database of (?P<name>[a-z0-9-]+) "
                    r"\[(?P<code>w[0-9a-f]{12})\]\?$")
ENDED_HERE = ("accepted", "forgotten", "released", "removed")
OK_LABEL = "Allow"


def files_in(answer: Any) -> Iterator[tuple[str, str]]:
    """The (id, name) of each file a Drive tool's answer holds, at any depth (title or name; a JSON text is read).

    Args:
        answer: the tool's response (a dict, a list, or text).

    Yields:
        (file id, file name) pairs.
    """
    if isinstance(answer, str):
        try:
            answer = json.loads(answer)
        except ValueError:
            return
    if isinstance(answer, dict):
        name = answer.get("title") or answer.get("name")
        if isinstance(answer.get("id"), str) and isinstance(name, str):
            yield answer["id"], name
        for value in answer.values():
            yield from files_in(value)
    elif isinstance(answer, list):
        for value in answer:
            yield from files_in(value)


def stamp_ms(stamp: str) -> int:
    """A copy's UTC time stamp (20261116T095800Z) in ms.

    Args:
        stamp: the stamp of a copy's name.

    Returns:
        Milliseconds since the epoch.
    """
    return calendar.timegm(time.strptime(stamp, "%Y%m%dT%H%M%SZ")) * 1000


def seen(port: PlanStore, event: Any) -> list[str]:
    """Keep each copy of this session's delegated plan that a Drive tool's answer shows, on its child's crew entry
    (the newest by time; only when the copy's session is the child's own). The answer is Drive's, read by the hook.

    Args:
        port: the ledger port.
        event: a PostToolUse hook call of an MCP tool.

    Returns:
        One note per child newly seen in the store.
    """
    if not str(event.tool or "").startswith("mcp__"):
        return []
    text = event.response if isinstance(event.response, str) else json.dumps(event.response, ensure_ascii=False)
    if "__orch.pd-" not in (text or ""):
        return []
    ticket = port.ticket(event.session) if event.session else None
    if not ticket or not (ticket.get("plan") or {}).get("children") or not ticket.get("crew"):
        return []
    found = {}
    for file_id, name in files_in(event.response):
        m = COPY.match(name)
        entry = ticket["crew"].get(m["name"]) if m and m["draft"] == ticket.get("draft") else None
        own = {session_part(entry.get("sid")), session_part((entry.get("receipt") or {}).get("session"))} \
            if entry else set()
        if entry and m["session"] in own - {"nosession"}:
            copy = {"fileId": file_id, "title": name, "at": stamp_ms(m["stamp"])}
            if copy["at"] >= found.get(m["name"], {}).get("at", -1):
                found[m["name"]] = copy

    def keep(con: sqlite3.Connection, rec: Recorder) -> list[str]:
        fresh, notes = tickets.latest(con, event.session), []
        crew = dict(fresh.get("crew") or {})
        for name, copy in found.items():
            if copy["at"] > (crew[name].get("stored") or {}).get("at", -1):
                crew[name] = {**crew[name], "stored": copy}
                notes.append(f"Verified in the store: {name}'s database {copy['title']} (Drive file {copy['fileId']}).")
        tickets.save(con, {**fresh, "crew": crew})
        return notes
    return port.write(keep) if found else []


def code_of(draft: str, name: str) -> str:
    """The code of the waiver of one child of one plan.

    Args:
        draft: the plan's desk id.
        name: the child's name.

    Returns:
        "w" and 12 hex characters.
    """
    return "w" + hashlib.sha256(json.dumps([draft, name]).encode("utf-8")).hexdigest()[:12]


def waiver_question(draft: str, name: str) -> dict[str, Any]:
    """The form that lets a plan be done without a child's database: only for a child that can never upload.

    Args:
        draft: the plan's desk id.
        name: the child's name.

    Returns:
        One AskUserQuestion question.
    """
    return {"question": f"Close plan {draft} without the database of {name} [{code_of(draft, name)}]?",
            "header": "No database", "multiSelect": False,
            "options": [{"label": OK_LABEL, "description": f"{name}'s session cannot upload; close the plan without it"},
                        {"label": "Deny", "description": "keep the plan open until its database is in the store"}]}


def waiver_accepts(port: PlanStore, answers: dict[str, str]) -> list[str]:
    """Keep the user's Allow to a waiver form; the notes for the model.

    Args:
        port: the harness ledger.
        answers: {form question: the label the user chose}.

    Returns:
        One note per waiver allowed.
    """
    notes = []
    for q, label in (answers or {}).items():
        m = WAIVER.match(str(q))
        if not m or str(label).strip() != OK_LABEL:
            continue
        port.write(lambda con, rec, code=m["code"]: con.execute(
            "INSERT OR REPLACE INTO pl_asks (sid, key, at, used) VALUES ('', ?, ?, 0)", (code, int(time.time() * 1000))))
        notes.append(f"GATE: the user allowed plan {m['draft']} to close without the database of {m['name']}.")
    return notes


def synced(port: PlanStore, ticket: Ticket, name: str) -> Optional[str]:
    """Why a child of the plan is not synced, or None when it is (its copy is in the store, not older than its
    handback) or the user waived it.

    Args:
        port: the ledger port.
        ticket: the parent's ticket.
        name: the child's name.

    Returns:
        "no copy found" or "its newest copy is older than its handback", or None.
    """
    entry = (ticket.get("crew") or {}).get(name, {})
    stored, handed = entry.get("stored") or {}, int((entry.get("receipt") or {}).get("at") or 0)
    if stored and stored.get("at", 0) >= handed - 1000:
        return None
    if port.rows("SELECT 1 AS x FROM pl_asks WHERE sid = '' AND key = ?", (code_of(ticket["draft"], name),)):
        return None
    return "its newest copy is older than its handback" if stored else "no copy found"


def missing(port: PlanStore, ticket: Ticket) -> list[tuple[str, str]]:
    """The children that ended and are not synced: (name, why).

    Args:
        port: the ledger port.
        ticket: the parent's ticket.

    Returns:
        Their names and why, in the plan's order.
    """
    out = []
    for card in ticket["plan"].get("children", []):
        if (ticket.get("crew") or {}).get(card["name"], {}).get("state") in ENDED_HERE:
            why = synced(port, ticket, card["name"])
            if why:
                out.append((card["name"], why))
    return out


def ask_text(ticket: Ticket, folder: str, gaps: list[tuple[str, str]], db: str = "") -> str:
    """What the parent does for the children not synced: search the whole store by the copies' names (a child's final
    copy is in its subtask folder, its safety copies in the db folder, older runs' copies in the store folder; the
    hook reads the answers), search again later, or ask the user's waiver for a child that did not upload (no message
    reaches a child).

    Args:
        ticket: the parent's ticket.
        folder: the store's Drive folder id.
        gaps: (name, why) of each child not synced.
        db: the store's db folder's id (store.place); kept for the callers, the search reads every folder.

    Returns:
        The text for the model.
    """
    draft, crew = ticket["draft"], ticket.get("crew") or {}
    lines = [f"Not synced yet: {', '.join(f'{n} ({w})' for n, w in gaps)}. The plan is done only when each child's "
             "database is in the store.",
             f"1. Search the store with your Google Drive tool: search_files with the query: title contains "
             f"'orch.{draft}.' and '{folder}' in ancestors. The harness reads Drive's answer itself; then run the same "
             "action again."]
    for name, _ in gaps:
        lines.append(f"2. A child saves its ledger at its handback, and nothing reaches it afterwards (parent and child "
                     f"talk only through its branch): if {name} has no copy, search again a little later.")
        lines.append(f"3. If {name} still has no copy (its session {crew[name].get('sid')} did not upload): ask the user "
                     f"exactly {json.dumps({'questions': [waiver_question(draft, name)]}, ensure_ascii=False)}")
    return "\n".join(lines)
