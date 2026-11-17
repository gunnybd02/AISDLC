"""Activity: what the harness records of each action by itself (docs/12-ledger.md), as rows of the caller's
transaction, so a call is recorded whole or not at all.
- a turn (pl_turns): opened by a prompt, closed when the reply ends; its number places everything else;
- a prompt (pl_prompts): under its turn's number, secrets masked, cut at 64 KB, marked when it is not the user's own
  words (a system notification, a peer's message);
- a peer's message: one peer span where it arrives, the answer of the notifications tool, with sender and size;
- a judged tool or shell event: one act_tool_calls row, one gate span (pl_spans), and one act_rule_decisions row per
  finding with the word Claude Code was given; the harness judging a write from inside (the server's gate, its commit)
  keeps its gate span and findings and no second tool-call row;
- a run of a harness action: one tool span with the names of its arguments, never their values;
- a session (sessions): its row when first met, with the project and the release it runs; its epoch rises by one
  when its context is compacted or cleared;
- a skill load (act_skill_loads): the skill, the route (guide, tool, read, slash) and the session's epoch then, so
  what a session knows now is what it loaded in its current epoch."""
from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from collections.abc import Collection, Iterable, Sequence
from typing import TYPE_CHECKING, Any, Optional

from harness.utils.contracts import CLAUDE_DECISION, Event, Finding
from harness.utils.ledger.mask import REDACTED, mask, stored
from harness.utils.shapes import ApprovedPlan

if TYPE_CHECKING:
    from harness.utils.ledger.recorder import Recorder

PROMPT_MOST = 65536
PEER = "<cross-session-message"  # how the host wraps a message another session sent
NOTICE = "<task-notification>"  # how the host wraps a system notification: never the user's own words
PEER_MESSAGE = re.compile(r'<cross-session-message from-session="([^"]*)">(.*?)</cross-session-message>', re.S)
NOTIFICATIONS = "ReadNotifications"  # the tool whose answer holds the messages of other sessions
HARNESS = "mcp__harness__"  # the prefix Claude Code gives the harness's own tools
RUN_TOOL = "mcp__harness__run"
INNER_TOOLS = ("HarnessCommit", "HarnessGit")  # events the harness builds to judge its own commit or git line
SKILL_FILE = re.compile(r"[\\/](?:skill_docs|skills)[\\/]([A-Za-z0-9_.-]+)[\\/]SKILL\.md$")
SLASH = re.compile(r"^/([A-Za-z0-9_.:-]+)(?:\s|$)")
ANNOTATED = ("span", "turn", "session", "plan")  # what a judgment is about
MODEL = "LLM"  # the annotator of every row the model writes: evidence for a pattern, never authority
NEW_EPOCH = ("compact", "clear")  # the sources of a session start after which earlier loads no longer count


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
                "(?, ?, ?, ?, ?, ?, 'live', '', ?)", (sid, n, kept, chars, cut, int(from_others(text)), now()))


def from_others(text: str) -> bool:
    """Whether a prompt is not the user's own words: a system notification, or a message another session sent.

    Args:
        text: the prompt as the hook got it.

    Returns:
        True when it starts with the host's notification wrapper or holds the wrapper of a peer's message.
    """
    return str(text).lstrip().startswith(NOTICE) or PEER in str(text)


def peers(con: sqlite3.Connection, event: Event) -> int:
    """Keep the messages of other sessions where they arrive: the answer of the notifications tool. One peer span per
    message, with its sender and size, never its text.

    Args:
        con: the connection of the transaction.
        event: the hook call (only a PostToolUse of the notifications tool is read).

    Returns:
        The number of messages kept.
    """
    if event.kind != "PostToolUse" or event.tool != NOTIFICATIONS or not event.session:
        return 0
    found = [m for text in texts(event.response) for m in PEER_MESSAGE.findall(text)]
    for sender, body in found:
        span(con, event.session, "peer", "ok", sender[:200], {"from": sender, "chars": len(body.strip())})
    return len(found)


def texts(value: Any) -> list[str]:
    """Every string inside a tool's answer, as it is: the notifications tool answers an object whose messages sit in
    notifications[].content, and its JSON text would escape the quotes the wrapper is found by (live check of
    2026-11-17).

    Args:
        value: the answer (a string, a list, an object, or anything else).

    Returns:
        Its strings, depth first; a list holds at most 200 of them.
    """
    if isinstance(value, str):
        return [value]
    items = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    return [t for item in list(items)[:200] for t in texts(item)]


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
    """The name a call is recorded under: "<block>.<action>" for a run of a harness action, "guide.<name>" for a guide
    call, "find" for a find call, else the tool's name.

    Args:
        event: the hook call.

    Returns:
        The name.
    """
    given = event.input if isinstance(event.input, dict) else {}
    if event.tool == RUN_TOOL and given.get("block") and given.get("action"):
        return f"{given['block']}.{given['action']}"
    if event.tool == HARNESS + "guide":
        return f"guide.{given.get('name') or given.get('block') or ''}".rstrip(".")
    if event.tool == HARNESS + "find":
        return "find"
    return event.tool or ""


def inner(event: Event) -> bool:
    """Whether an event is the harness judging a call from inside (the server's write gate, its commit or git line),
    not a call Claude Code makes: such an event keeps its gate span and findings and no tool-call row of its own.

    Args:
        event: the event judged.

    Returns:
        True for an event of INNER_TOOLS, or a run of a harness action that names its effect (the server's gate).
    """
    given = event.input if isinstance(event.input, dict) else {}
    return event.tool in INNER_TOOLS or (event.tool == RUN_TOOL and "effect" in given)


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
        if not inner(event):  # one tool-call row per call: the hook's, or the tool span when no hook runs
            con.execute("INSERT INTO act_tool_calls (sid, agent, tool, service, at, plan_id, uid) VALUES (?, '', ?, '', "
                        "?, ?, ?)", (sid, name, now(), plan["id"] if plan else 0, uuid.uuid4().hex))
        span(con, sid, "gate", "denied" if word in CLAUDE_DECISION.values() else "ok", name,
             {"decision": word, "rules": sorted({f.kind for f in findings})})
    for finding in findings:
        rec.insert(con, "act_rule_decisions", {
            "uid": uuid.uuid4().hex, "sid": sid, "agent": "", "plan_id": plan["id"] if plan else None,
            "rule": finding.kind, "kind": "finding", "tool": event.tool, "service": "", "verdict": word,
            "detail": finding.detail, "at": now()})


def session_seen(con: sqlite3.Connection, sid: str, project: str, release: str) -> None:
    """Make sure the session has its row, with the project and the release it runs; a row that is there keeps its
    times, and any row that still has no project gets this one. A new row's last time is 0: last_at moves only at a
    prompt or a call of the harness's tools (touch_session), which is how the MCP server knows who calls it.

    Args:
        con: the connection of the transaction.
        sid: the session id ("" changes nothing).
        project: the project's key (the root commit of the home, else a hash of its path).
        release: the release the code runs from (its first 12 characters), or "work" for the work tree.
    """
    if not sid:
        return
    at = now()
    con.execute("INSERT OR IGNORE INTO sessions (sid, started_at, last_at, project, harness_ver) VALUES (?, ?, 0, ?, ?)",
                (sid, at, project, release))
    con.execute("UPDATE sessions SET harness_ver = ? WHERE sid = ? AND harness_ver != ?", (release, sid, release))
    if project:
        con.execute("UPDATE sessions SET project = ? WHERE project = ''", (project,))


def epoch_of(con: sqlite3.Connection, sid: str) -> int:
    """The session's epoch now.

    Args:
        con: an open connection to the ledger.
        sid: the session id.

    Returns:
        Its epoch; 0 for a session with no row.
    """
    row = con.execute("SELECT epoch FROM sessions WHERE sid = ?", (sid,)).fetchone()
    return row[0] if row else 0


def epoch_up(con: sqlite3.Connection, sid: str) -> None:
    """The session's context was compacted or cleared: its epoch rises by one, so earlier loads no longer count.

    Args:
        con: the connection of the transaction.
        sid: the session id.
    """
    con.execute("UPDATE sessions SET epoch = epoch + 1, last_at = ? WHERE sid = ?", (now(), sid))


def skill_load(con: sqlite3.Connection, sid: str, skill: str, via: str) -> None:
    """Keep that the session loaded a skill, with the route and its epoch then.

    Args:
        con: the connection of the transaction.
        sid: the session id.
        skill: the skill's name.
        via: the route: guide, tool (the Skill tool), read (a Read of its file) or slash (a prompt that starts with
            /<name>).
    """
    con.execute("INSERT INTO act_skill_loads (sid, agent, skill, via, epoch, at, uid) VALUES (?, '', ?, ?, ?, ?, ?)",
                (sid, skill, via, epoch_of(con, sid), now(), uuid.uuid4().hex))


def loaded(con: sqlite3.Connection, sid: str) -> set[str]:
    """The skills the session loaded in its current epoch: what it knows now.

    Args:
        con: an open connection to the ledger.
        sid: the session id.

    Returns:
        The distinct skill names.
    """
    return {r[0] for r in con.execute("SELECT DISTINCT skill FROM act_skill_loads WHERE sid = ? AND epoch = ?",
                                      (sid, epoch_of(con, sid)))}


def skill_seen(event: Event, known: Collection[str]) -> Optional[tuple[str, str]]:
    """The skill a hook call loaded outside the guide tool, and its route.

    Args:
        event: the hook call.
        known: the names of the library's skills; only these count.

    Returns:
        (skill, "tool") after the Skill tool ran, (skill, "read") after a Read of its SKILL.md, (skill, "slash") for a
        prompt that starts with /<skill>; None for any other call or a name that is no skill of the library.
    """
    given = event.input if isinstance(event.input, dict) else {}
    found: Optional[tuple[str, str]] = None
    if event.kind == "PostToolUse" and event.tool == "Skill":
        found = (str(given.get("skill") or "").lstrip("/").split(":")[-1], "tool")
    elif event.kind == "PostToolUse" and event.tool == "Read":
        m = SKILL_FILE.search(str(given.get("file_path") or ""))
        found = (m.group(1), "read") if m else None
    elif event.kind == "UserPromptSubmit":
        m = SLASH.match(str(given.get("prompt") or "").lstrip())
        found = (m.group(1).split(":")[-1], "slash") if m else None
    return found if found and found[0] in known else None


def annotate(con: sqlite3.Connection, sid: str, given: dict[str, Any]) -> str:
    """Keep one judgment of the model about a span, a turn, a session or a plan (pl_annotations). The annotator is
    always the model's: no gate reads such a row.

    Args:
        con: the connection of the transaction.
        sid: the calling session ("" when none is known).
        given: {unit, ref, name, identifier, label?, score?, explanation?} as the model sent it.

    Returns:
        "" when the row was kept; else why it was not (a missing field, an unknown unit, a score that is no number):
        nothing is written then.
    """
    for key in ("unit", "ref", "name", "identifier"):
        if not isinstance(given.get(key), str) or not given[key].strip():
            return f"annotate needs {key}"
    if given["unit"] not in ANNOTATED:
        return f"annotate needs unit to be one of {', '.join(ANNOTATED)}"
    score = given.get("score")
    if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))):
        return "annotate needs score to be a number"
    why = " ".join(str(given.get("explanation") or "").split())
    con.execute("INSERT INTO pl_annotations (uid, sid, unit, ref, name, label, score, explanation, annotator, identifier, "
                "at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, sid, given["unit"], given["ref"].strip()[:120], given["name"].strip()[:80],
                 str(given.get("label") or "").strip()[:80], score, REDACTED if mask(why) != why else why[:300], MODEL,
                 given["identifier"].strip()[:80], now()))
    return ""
