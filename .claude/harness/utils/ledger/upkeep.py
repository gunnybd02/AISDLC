"""Upkeep of the ledger (docs/12-ledger.md), three things in this order, each safe to run again:
1. roll up: each finished UTC day that has rows in act_tool_calls, act_skill_loads or act_rule_decisions and is not in
   rolled_days is counted into usage_daily, by the session's project and release; all days of a run are one
   transaction. Today is never rolled: a day is counted once, after it is over.
2. prune: rows older than 180 days leave act_tool_calls, act_rule_decisions and pl_prompts, only after a roll-up
   that finished without error. Everything else is kept.
3. backup: one copy of the ledger a day (VACUUM INTO) in state/backups/, kept as the newest 7, the newest of each of
   the last 4 weeks (Monday first, UTC) and of the last 6 months.
Day totals are so kept for good and the raw rows of three tables for 180 days. It runs after a commit and at session
start; a second run on the same day changes nothing."""
from __future__ import annotations

import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

KEEP_DAYS = 180
PRUNED = ("act_tool_calls", "act_rule_decisions", "pl_prompts")
SOURCES = (("tool", "act_tool_calls", "t.tool", "t.service", "0"),
           ("skill", "act_skill_loads", "t.skill", "''", "0"),
           ("rule", "act_rule_decisions", "t.rule", "t.service", "SUM(t.verdict IN ('deny', 'block', 'ask'))"))
DAY = "date(t.at / 1000, 'unixepoch')"
BACKUPS = "backups"
NEWEST, WEEKS, MONTHS = 7, 4, 6


def day_of(ms: int) -> str:
    """The UTC day of a time.

    Args:
        ms: milliseconds since the epoch.

    Returns:
        "YYYY-MM-DD".
    """
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def rollup(con: sqlite3.Connection, now_ms: int) -> list[str]:
    """Count each finished day not rolled yet into usage_daily and mark it rolled.

    Args:
        con: the connection of the transaction.
        now_ms: the time now in ms; its UTC day is today and is not rolled.

    Returns:
        The days rolled, in order.
    """
    today, days = day_of(now_ms), set()
    for _, table, _, _, _ in SOURCES:
        days |= {r[0] for r in con.execute(
            f"SELECT DISTINCT {DAY} FROM {table} t WHERE t.at IS NOT NULL AND {DAY} < ? AND {DAY} NOT IN "
            "(SELECT day FROM rolled_days)", (today,)) if r[0]}
    for day in sorted(days):
        for kind, table, name, service, blocks in SOURCES:
            con.execute(
                "INSERT INTO usage_daily (day, project, harness_ver, kind, name, service, calls, sessions, blocks) "
                f"SELECT ?, COALESCE(s.project, ''), COALESCE(s.harness_ver, ''), ?, COALESCE({name}, ''), "
                f"COALESCE({service}, ''), COUNT(*), COUNT(DISTINCT t.sid), COALESCE({blocks}, 0) FROM {table} t "
                f"LEFT JOIN sessions s ON s.sid = t.sid WHERE {DAY} = ? GROUP BY 2, 3, 5, 6 "
                "ON CONFLICT(day, project, harness_ver, kind, name, service) DO UPDATE SET calls = calls + "
                "excluded.calls, blocks = blocks + excluded.blocks, sessions = MAX(sessions, excluded.sessions)",
                (day, kind, day))
        con.execute("INSERT OR IGNORE INTO rolled_days (day, at) VALUES (?, ?)", (day, now_ms))
    return sorted(days)


def prune(con: sqlite3.Connection, now_ms: int) -> dict[str, int]:
    """Delete the rows older than KEEP_DAYS days from the three pruned tables.

    Args:
        con: the connection of the transaction.
        now_ms: the time now in ms.

    Returns:
        {table: rows deleted}, only tables that lost rows.
    """
    limit, out = now_ms - KEEP_DAYS * 86400000, {}
    for table in PRUNED:
        gone = con.execute(f"DELETE FROM {table} WHERE at < ?", (limit,)).rowcount
        if gone:
            out[table] = gone
    return out


def kept_days(days: list[str], today: str) -> set[str]:
    """Which daily backups stay.

    Args:
        days: the days ("YYYY-MM-DD") that have a backup.
        today: today's UTC day.

    Returns:
        The newest NEWEST days, the newest day of each of the last WEEKS weeks (Monday first) and of each of the last
        MONTHS months, today's week and month counted.
    """
    have = sorted(days)
    keep = set(have[-NEWEST:])
    now = date.fromisoformat(today)
    monday = now - timedelta(days=now.weekday())
    for back in range(WEEKS):
        start = monday - timedelta(weeks=back)
        week = [d for d in have if start <= date.fromisoformat(d) < start + timedelta(weeks=1)]
        keep |= set(week[-1:])
    year, month = now.year, now.month
    for _ in range(MONTHS):
        keep |= set([d for d in have if d.startswith(f"{year:04d}-{month:02d}-")][-1:])
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return keep


def backup(con: sqlite3.Connection, ledger_path: str | Path, now_ms: int) -> str:
    """Make today's copy of the ledger when there is none yet, and take away the copies that no longer stay.

    Args:
        con: a connection to the ledger in autocommit mode, with no transaction open (VACUUM INTO needs none).
        ledger_path: the ledger's file; the copies go to backups/ beside it.
        now_ms: the time now in ms.

    Returns:
        The name of the copy made, or "" when today's copy was there already.

    Raises:
        sqlite3.Error: the copy cannot be made.
        OSError: the folder cannot be written.
    """
    folder, today = Path(ledger_path).parent / BACKUPS, day_of(now_ms)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"harness-{today}.db"
    made = ""
    if not target.exists():
        con.execute("VACUUM INTO ?", (str(target),))
        made = target.name
    days = {p.stem[len("harness-"):]: p for p in folder.glob("harness-????-??-??.db")}
    for day in set(days) - kept_days(list(days), today):
        days[day].unlink()
    return made


def now() -> int:
    """The time now in ms.

    Returns:
        Milliseconds since the epoch.
    """
    return int(time.time() * 1000)
