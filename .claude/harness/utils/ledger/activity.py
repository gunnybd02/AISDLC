"""Activity: what the harness records of each action by itself (docs/12-ledger.md), as rows of the caller's
transaction, so a call is recorded whole or not at all.
- a turn (pl_turns): opened by a prompt, closed when the reply ends; its number places everything else;
- a prompt (pl_prompts): under its turn's number, secrets masked, cut at 64 KB, marked when another session sent it;
- a judged tool or shell event: one act_tool_calls row, one gate span (pl_spans), and one act_rule_decisions row per
  finding with the word Claude Code was given;
- a run of a harness action: one tool span with the names of its arguments, never their values."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any, Optional

from harness.utils.contracts import CLAUDE_DECISION, Event, Finding
from harness.utils.ledger.mask import stored
from harness.utils.shapes import ApprovedPlan

if TYPE_CHECKING:
    from harness.utils.ledger.recorder import Recorder

PROMPT_MOST = 65536
PEER = "<cross-session-message"  # how the host wraps a message another session sent
RUN_TOOL = "mcp__harness__run"


def now() -> int:
    """The time now in ms.

    Returns:
        Milliseconds since the epoch.
    """
    return int(time.time() * 1000)


def turn_now(con: sqlite3.Connection, sid: str) -> int:
    """The number of the session's newest turn.

    Args:
        con: an open connection to the ledger.
        sid: the session id.

    Returns:
        The highest turn number of the session; 0 when it has none.
    """
    return con.execute("SELECT MAX(n) FROM pl_turns WHERE sid = ?", (sid,)).fetchone()[0] or 0


def turn_open(con: sqlite3.Connection, sid: str, prompt_len: int) -> int:
    """Open a turn at a prompt; a turn still open is closed first.

    Args:
        con: the connection of the transaction.
        sid: the session id.
        prompt_len: the length of the prompt in characters.

    Returns:
        The new turn's number: one more than the session's highest turn or prompt number (a ledger made before turns
        were kept holds prompts without turns).
    """
    at = now()
    con.execute("UPDATE pl_turns SET ended_at = ? WHERE sid = ? AND ended_at = 0", (at, sid))
    last = con.execute("SELECT MAX(n) FROM pl_prompts WHERE sid = ?", (sid,)).fetchone()[0] or 0
    n = 1 + max(turn_now(con, sid), last)
    con.execute("INSERT INTO pl_turns (sid, n, plan_id, ticket, phase, prompt_len, started_at, ended_at) VALUES "
                "(?, ?, 0, '', '', ?, ?, 0)", (sid, n, prompt_len, at))
    return n


def turn_close(con: sqlite3.Connection, sid: str) -> None:
    """Close the session's open turn: the reply ended.

    Args:
        con: the connection of the transaction.
        sid: the session id.
    """
    con.execute("UPDATE pl_turns SET ended_at = ? WHERE sid = ? AND ended_at = 0", (now(), sid))


def prompt(con: sqlite3.Connection, sid: str, n: int, text: str) -> None:
    """Keep a prompt under its turn's number: masked, cut at PROMPT_MOST characters, marked when a peer sent it.

    Args:
        con: the connection of the transaction.
        sid: the session id.
        n: the turn's number.
        text: the prompt as typed or sent.
    """
    kept, chars, cut = stored(text, PROMPT_MOST)
    con.execute("INSERT OR REPLACE INTO pl_prompts (sid, n, text, chars, cut, from_peer, source, uuid, at) VALUES "
                "(?, ?, ?, ?, ?, ?, 'live', '', ?)", (sid, n, kept, chars, cut, int(PEER in text), now()))


def span(con: sqlite3.Connection, sid: str, kind: str, status: str, name: str, attrs: dict[str, Any]) -> None:
    """Keep one span: a unit of activity of a session, placed in its newest turn.

    Args:
        con: the connection of the transaction.
        sid: the session id ("" when none is known).
        kind: tool (a run of a harness action), gate (a decision of the guard), llm (a reply of the model).
        status: ok, error or denied.
        name: the tool or action, for llm the model.
        attrs: its detail as a JSON object (argument names, the decision and its rules...).
    """
    con.execute("INSERT INTO pl_spans (uid, sid, turn, parent, kind, status, name, ms, done, attrs, at) VALUES "
                "(?, ?, ?, '', ?, ?, ?, 0, 1, ?, ?)", (uuid.uuid4().hex, sid, turn_now(con, sid) if sid else 0, kind,
                                                      status, name[:200], json.dumps(attrs, ensure_ascii=False), now()))


def tool_of(event: Event) -> str:
    """The name a call is recorded under: "<block>.<action>" for a run of a harness action, else the tool's name.

    Args:
        event: the hook call.

    Returns:
        The name.
    """
    given = event.input if isinstance(event.input, dict) else {}
    if event.tool == RUN_TOOL and given.get("block") and given.get("action"):
        return f"{given['block']}.{given['action']}"
    return event.tool or ""


def arg_names(given: Any) -> list[str]:
    """The names of the arguments of a call, never their values.

    Args:
        given: the arguments as sent (an object, or anything else).

    Returns:
        The keys, sorted; [] when given is no object.
    """
    return sorted(str(k) for k in given) if isinstance(given, dict) else []


def record_call(con: sqlite3.Connection, rec: Recorder, event: Event, plan: Optional[ApprovedPlan], word: str,
                findings: Iterable[Finding] | Sequence[Finding]) -> None:
    """Keep what one hook call was: for a tool or shell event before it runs, a tool-call row and a gate span; for any
    call, one rule-decision row per finding. All in the caller's transaction.

    Args:
        con: the connection of the transaction.
        rec: the recorder of the transaction.
        event: the hook call.
        plan: the plan in force in its session, or None.
        word: the word Claude Code was given for the call (contracts.CLAUDE_DECISION, or the decision itself).
        findings: the findings of the verdict.
    """
    sid, findings = event.session or "", list(findings)
    if event.kind == "PreToolUse":
        name = tool_of(event)
        con.execute("INSERT INTO act_tool_calls (sid, agent, tool, service, at, plan_id, uid) VALUES (?, '', ?, '', ?, "
                    "?, ?)", (sid, name, now(), plan["id"] if plan else 0, uuid.uuid4().hex))
        span(con, sid, "gate", "denied" if word in CLAUDE_DECISION.values() else "ok", name,
             {"decision": word, "rules": sorted({f.kind for f in findings})})
    for finding in findings:
        rec.insert(con, "act_rule_decisions", {
            "uid": uuid.uuid4().hex, "sid": sid, "agent": "", "plan_id": plan["id"] if plan else None,
            "rule": finding.kind, "kind": "finding", "tool": event.tool, "service": "", "verdict": word,
            "detail": finding.detail, "at": now()})
