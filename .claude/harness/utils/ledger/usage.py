"""Usage: the tokens of a session, read from its transcript by the harness (docs/12-ledger.md), as rows of the
caller's transaction. Claude Code writes one line per content block of a reply, each with the reply's id, model and
usage; read_new reads the whole new lines from the offset kept for the file and keeps
- pl_usage: one row per message and token type (input, output, cache_write, cache_read) with tokens above 0; a
  message already kept is skipped, so reading twice changes nothing;
- pl_spans: one llm span per new message, in the turn it fell in;
- pl_session_meta: the model and effort the session last ran with;
- pl_usage_offsets: how far the file is read.
Usage outlives the transcript. pl_prices holds list prices (seed, only into an empty table): the cost of the retro
views is tokens times these rates, a conversion and not a bill; a model with no price costs 0 there."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from harness.utils.contracts import now

TYPES = {"input_tokens": "input", "output_tokens": "output", "cache_creation_input_tokens": "cache_write",
         "cache_read_input_tokens": "cache_read"}
PRICED_FROM = "2025-01-01"
# List prices in USD per million tokens (input, output, cache read), as published on 2026-11-03. A cache write is
# 1.25 times the input price. Each pattern is one exact model id, so no usage row matches two prices.
LIST_PRICES = {
    "claude-fable-5-2": (8.0, 40.0, 0.20), "claude-mythos-5-2": (8.0, 40.0, 0.20),
    "claude-fable-5-1": (10.0, 50.0, 1.0), "claude-mythos-5-1": (10.0, 50.0, 1.0), "claude-fable-5": (10.0, 50.0, 1.0),
    "claude-opus-5-5": (4.0, 20.0, 0.20), "claude-opus-5": (5.0, 25.0, 0.5), "claude-opus-4-8": (5.0, 25.0, 0.5),
    "claude-opus-4-7": (5.0, 25.0, 0.5), "claude-opus-4-6": (5.0, 25.0, 0.5),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10), "claude-sonnet-5": (2.0, 10.0, 0.2), "claude-sonnet-4-6": (3.0, 15.0, 0.3),
    "claude-haiku-5-5": (0.10, 0.50, 0.01), "claude-haiku-4-5": (1.0, 5.0, 0.1),
}


def at_of(stamp: Any) -> int:
    """The time of a transcript line in ms.

    Args:
        stamp: the line's timestamp (ISO 8601 text, as Claude Code writes it).

    Returns:
        Milliseconds since the epoch; the time now when the stamp cannot be read.
    """
    try:
        return int(datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return now()


def new_lines(path: str | Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    """The whole lines of a transcript after an offset, as JSON objects.

    Args:
        path: the transcript file (JSON lines).
        offset: the byte the file is read from; one beyond the file's size reads it from its start (a file written
            again shorter).

    Returns:
        (the lines that are JSON objects, the offset after the last whole line); a half-written last line waits.

    Raises:
        OSError: the file cannot be read.
    """
    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        start = offset if 0 <= offset <= size else 0
        f.seek(start)
        data = f.read()
    whole = data[:data.rfind(b"\n") + 1]
    lines = []
    for raw in whole.splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict):
            lines.append(line)
    return lines, start + len(whole)


def messages(lines: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """The replies of the model among transcript lines, one per message id.

    Args:
        lines: transcript lines as JSON objects.

    Yields:
        {id, model, effort, at, tokens: {token type: count above 0}} for each reply that names its id and usage; a
        message that spans several lines is given once, with the usage of its last line.
    """
    found: dict[str, dict[str, Any]] = {}
    for line in lines:
        message = line.get("message")
        if line.get("type") != "assistant" or not isinstance(message, dict):
            continue
        used, mid = message.get("usage"), message.get("id")
        if not isinstance(used, dict) or not isinstance(mid, str) or not mid:
            continue
        tokens = {kind: used[key] for key, kind in TYPES.items()
                  if isinstance(used.get(key), int) and not isinstance(used[key], bool) and used[key] > 0}
        found[mid] = {"id": mid, "model": str(message.get("model") or ""), "effort": str(line.get("effort") or ""),
                      "at": at_of(line.get("timestamp")), "tokens": tokens}
    yield from found.values()


def offset_of(con: sqlite3.Connection, sid: str, name: str) -> int:
    """How far a transcript file is read.

    Args:
        con: an open connection to the ledger.
        sid: the session id.
        name: the transcript's file name.

    Returns:
        The byte offset kept; 0 for a file not read yet.
    """
    row = con.execute("SELECT offset FROM pl_usage_offsets WHERE sid = ? AND file = ?", (sid, name)).fetchone()
    return row[0] if row else 0


def kept(con: sqlite3.Connection, sid: str, mid: str) -> bool:
    """Whether a message's usage is in the ledger already.

    Args:
        con: an open connection to the ledger.
        sid: the session id.
        mid: the message id.

    Returns:
        True when pl_usage holds a row of the message.
    """
    return con.execute("SELECT 1 FROM pl_usage WHERE sid = ? AND message_id = ?", (sid, mid)).fetchone() is not None


def pending(con: sqlite3.Connection, sid: str, path: str | Path) -> tuple[int, int]:
    """What a transcript holds that the ledger lacks, without writing.

    Args:
        con: an open connection to the ledger.
        sid: the session id.
        path: the transcript file.

    Returns:
        (the messages not kept yet, their tokens), read from the offset kept.

    Raises:
        OSError: the file cannot be read.
    """
    lines, _ = new_lines(path, offset_of(con, sid, Path(path).name))
    new = [m for m in messages(lines) if m["tokens"] and not kept(con, sid, m["id"])]
    return len(new), sum(sum(m["tokens"].values()) for m in new)


def tokens_of(con: sqlite3.Connection, sid: str) -> int:
    """The tokens the ledger holds for a session.

    Args:
        con: an open connection to the ledger.
        sid: the session id.

    Returns:
        The sum of its pl_usage rows; 0 when it has none.
    """
    return con.execute("SELECT COALESCE(SUM(tokens), 0) FROM pl_usage WHERE sid = ?", (sid,)).fetchone()[0]


def read_new(con: sqlite3.Connection, sid: str, path: str | Path, main: bool = True) -> int:
    """Keep the usage of the new lines of a session's transcript.

    Args:
        con: the connection of the transaction.
        sid: the session id.
        path: the transcript file.
        main: True for the session's main transcript: its model and effort are the session's.

    Returns:
        The number of messages newly kept.

    Raises:
        OSError: the file cannot be read; nothing is kept then.
    """
    name = Path(path).name
    lines, end = new_lines(path, offset_of(con, sid, name))
    count, last = 0, None
    for m in messages(lines):
        last = m
        if not m["tokens"] or kept(con, sid, m["id"]):
            continue
        turn = con.execute("SELECT MAX(n) FROM pl_turns WHERE sid = ? AND started_at <= ?", (sid, m["at"])).fetchone()[0] or 0
        for kind, tokens in m["tokens"].items():
            con.execute("INSERT OR IGNORE INTO pl_usage (sid, message_id, token_type, tokens, model, file, turn, at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (sid, m["id"], kind, tokens, m["model"], name, turn, m["at"]))
        con.execute("INSERT INTO pl_spans (uid, sid, turn, parent, kind, status, name, ms, done, attrs, at) VALUES "
                    "(?, ?, ?, '', 'llm', 'ok', ?, 0, 1, ?, ?)", (uuid.uuid4().hex, sid, turn, m["model"], json.dumps(
                        {"model": m["model"], "message": m["id"], "file": name}), m["at"]))
        count += 1
    if main and last and last["model"]:
        con.execute("INSERT INTO pl_session_meta (sid, model, effort, at) VALUES (?, ?, ?, ?) ON CONFLICT(sid) DO UPDATE "
                    "SET model = excluded.model, effort = excluded.effort, at = excluded.at",
                    (sid, last["model"], last["effort"], now()))
    con.execute("INSERT INTO pl_usage_offsets (sid, file, offset, at) VALUES (?, ?, ?, ?) ON CONFLICT(sid, file) DO UPDATE "
                "SET offset = excluded.offset, at = excluded.at", (sid, name, end, now()))
    return count


def seed_prices(con: sqlite3.Connection) -> int:
    """Put the list prices into pl_prices when it holds none; a table with prices is left as it is.

    Args:
        con: the connection of the transaction.

    Returns:
        The number of price rows written (0 when the table had prices).
    """
    if con.execute("SELECT COUNT(*) FROM pl_prices").fetchone()[0]:
        return 0
    rows = []
    for model, (price_in, price_out, price_read) in LIST_PRICES.items():
        rows += [(model, "input", price_in), (model, "output", price_out), (model, "cache_write", price_in * 1.25),
                 (model, "cache_read", price_read)]
    con.executemany("INSERT INTO pl_prices (model_pattern, token_type, rate, per_tokens, from_date, at) VALUES "
                    f"(?, ?, ?, 1000000, '{PRICED_FROM}', {now()})", rows)
    return len(rows)


def transcripts(config_dir: Optional[str | Path] = None) -> list[tuple[str, Path]]:
    """The main transcripts of the sessions on this machine.

    Args:
        config_dir: Claude Code's own folder; None for CLAUDE_CONFIG_DIR, else ~/.claude.

    Returns:
        (session id, transcript file) of each <folder>/projects/<project>/<session id>.jsonl, sorted by path.
    """
    root = Path(config_dir or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
    return [(p.stem, p) for p in sorted(root.glob("*/*.jsonl"))]
