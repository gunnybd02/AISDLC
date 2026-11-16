"""RecordPort: the part of the ledger port that records what a session does, by itself (docs/12-ledger.md): the
rows of utils/ledger/activity.py, each call in one transaction. A recording fault never blocks or changes a call: it
leaves one line on the error stream and the call goes on."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from harness.assemble.engine.ledger_core import LedgerCore
from harness.utils.gateway.release import current
from harness.utils.git.run import GitError, git
from harness.utils.contracts import CLAUDE_DECISION, Event, Verdict
from harness.utils.ledger import activity, upkeep, usage, writes
from harness.utils.shapes import Change, Facts

NOT_RECORDED = "harness: not recorded in the ledger ({what}): {error}\n"


def project_of(home: str | Path) -> str:
    """The key of the project a home belongs to: the same for every clone of one repository.

    Args:
        home: the home (the .claude folder).

    Returns:
        The root commit of the home's repository cut to 16 characters; "path:" and 12 characters of a hash of its
        path when it has no commit.
    """
    try:
        roots = git(str(home), "rev-list", "--max-parents=0", "HEAD").split()
    except (GitError, OSError):
        roots = []
    if roots:
        return roots[-1][:16]
    return "path:" + hashlib.sha256(str(Path(home).resolve()).encode("utf-8")).hexdigest()[:12]


class RecordPort(LedgerCore):
    """The recording of a session's actions: its row, hook calls, runs of harness actions, skill loads, the end of a
    turn."""

    def home(self) -> Path:
        """The home this ledger belongs to.

        Returns:
            The .claude folder whose state/harness.db is the ledger.
        """
        return self.path.parent.parent

    def release(self) -> str:
        """The release the home runs.

        Returns:
            The first 12 characters of the release in force, or "work" when sessions run the work tree.
        """
        return (current(self.home()) or "work")[:12]

    def skill_names(self) -> set[str]:
        """The names of the library's skills, of the code this module belongs to.

        Returns:
            The folders of harness/mcp/skill_docs that hold a SKILL.md.
        """
        docs = Path(__file__).resolve().parents[2] / "mcp" / "skill_docs"
        return {p.parent.name for p in docs.glob("*/SKILL.md")}

    def touch_session(self, sid: str) -> None:
        """The session is at work now: the hook saw its prompt, or its call of the harness's MCP tools. Its row is
        made when new (with its project and release) and its last time moves.

        Args:
            sid: the session id ("" changes nothing).
        """
        if sid:
            def change(con: Any, rec: Any) -> None:
                self.seen(con, sid)
                con.execute("UPDATE sessions SET last_at = ? WHERE sid = ?", (activity.now(), sid))
            self.write(change)

    def seen(self, con: Any, sid: str) -> None:
        """Make sure a session has its row with its project and release (activity.session_seen); the project is read
        from git only for a session met the first time.

        Args:
            con: the connection of the transaction.
            sid: the session id ("" changes nothing).
        """
        if not sid:
            return
        row = con.execute("SELECT project FROM sessions WHERE sid = ?", (sid,)).fetchone()
        activity.session_seen(con, sid, row[0] if row and row[0] else project_of(self.home()), self.release())

    def session_started(self, sid: str, source: str) -> None:
        """A session began or its context was renewed: its row is made, and a compact or clear raises its epoch.

        Args:
            sid: the session id.
            source: the source Claude Code names for the start (startup, resume, clear, compact).
        """
        def change(con: Any, rec: Any) -> None:
            self.seen(con, sid)
            if sid and source in activity.NEW_EPOCH:
                activity.epoch_up(con, sid)
        self.recorded(f"session start ({source})", change)

    def skill_load(self, session: Optional[Callable[[], str]], skill: str, via: str) -> None:
        """Keep that the calling session loaded a skill.

        Args:
            session: session() -> the calling session's id, or None when the server has no such port.
            skill: the skill's name.
            via: the route (guide).
        """
        def change(con: Any, rec: Any) -> None:
            sid = session() if session else ""
            if sid:
                self.seen(con, sid)
                activity.skill_load(con, sid, skill, via)
        self.recorded(f"skill {skill}", change)

    def loaded(self, sid: str) -> set[str]:
        """The skills a session loaded in its current epoch.

        Args:
            sid: the session id.

        Returns:
            The distinct skill names; an empty set when there is no ledger yet.
        """
        return self.read(lambda con: activity.loaded(con, sid)) or set()

    def recorded(self, what: str, change: Change[Any]) -> None:
        """Run a recording in one transaction; a fault is told on the error stream and goes no further.

        Args:
            what: what is recorded, for the line a fault leaves.
            change: change(con, rec) makes the rows.
        """
        try:
            self.write(change)
        except Exception as e:  # recording never blocks or changes a call
            sys.stderr.write(NOT_RECORDED.format(what=what, error=f"{type(e).__name__}: {e}"))

    def record(self, event: Event, facts: Facts, verdict: Verdict) -> None:
        """Keep one hook call: its tool-call row and gate span when it is a tool or shell event before it runs, each
        finding with the word Claude Code was given, the shell line it runs and the files it wrote; the end of a reply
        that may end closes the turn.

        Args:
            event: the hook call.
            facts: the facts of the call (plan: the plan in force or None; writes: the files it writes).
            verdict: the verdict decide gave.
        """
        word = CLAUDE_DECISION.get(verdict.decision, verdict.decision)

        def change(con: Any, rec: Any) -> None:
            self.seen(con, event.session)
            activity.record_call(con, rec, event, facts.get("plan"), word, verdict.findings)
            writes.record(con, event, facts)
            load = activity.skill_seen(event, self.skill_names()) if event.session else None
            if load:
                activity.skill_load(con, event.session, *load)
            if event.kind == "Stop" and event.session and verdict.decision not in CLAUDE_DECISION:
                activity.turn_close(con, event.session)
        self.recorded(f"{event.kind} {event.tool or ''}".strip(), change)
        transcript = event.input.get("transcript_path") if isinstance(event.input, dict) else None
        if event.kind == "Stop" and event.session and transcript:  # the tokens of the turn, from the transcript
            self.recorded("usage", lambda con, rec: usage.read_new(con, event.session, transcript))

    def upkeep(self) -> str:
        """Run the ledger's upkeep (utils/ledger/upkeep.py): roll up finished days, then prune old rows only when the
        roll-up went well, then today's backup. It never raises: a fault is told on the error stream and in the text.

        Returns:
            What was done ("" when nothing was), or why a part was not.
        """
        said, at = [], upkeep.now()
        try:
            days = self.ledger.write(lambda con: upkeep.rollup(con, at))
            if days:
                said.append(f"rolled up {len(days)} day(s)")
            gone = self.ledger.write(lambda con: upkeep.prune(con, at))  # only after a roll-up without error
            if gone:
                said.append("pruned " + ", ".join(f"{n} of {t}" for t, n in sorted(gone.items())))
            made = upkeep.backup(self.ledger.con, self.path, at)
            if made:
                said.append(f"backup {made}")
        except Exception as e:
            sys.stderr.write(NOT_RECORDED.format(what="upkeep", error=f"{type(e).__name__}: {e}"))
            said.append(f"upkeep stopped ({type(e).__name__}: {e})")
        return "; ".join(said)

    def usage_backfill(self, write: bool) -> str:
        """Report the token usage the transcripts on this machine hold and the ledger lacks; write records it and
        seeds the list prices when there are none.

        Args:
            write: True to record the usage; False only reports it.

        Returns:
            One line per session with something new, the total, what was written, and what is not backfilled.
        """
        found = usage.transcripts()

        def look(con: Any, rec: Any) -> str:
            lines, total, seeded = [], 0, 0
            for sid, path in found:
                try:
                    count, tokens = usage.pending(con, sid, path)
                    if write and count:
                        self.seen(con, sid)
                        usage.read_new(con, sid, path)
                except OSError as e:
                    lines.append(f"{sid}: not read ({type(e).__name__})")
                    continue
                if count:
                    lines.append(f"{sid}: {count} message(s), {tokens} tokens")
                    total += count
            if write:
                seeded = usage.seed_prices(con)
            head = (f"{total} message(s) of {len(found)} transcript(s) " + ("recorded" if write else "are not in the "
                    "ledger yet; run it with write: true to record them") + ".")
            prices = [f"{seeded} list price(s) seeded (USD per million tokens, a conversion and not a bill)."] if seeded else []
            return "\n".join([head] + lines + prices + ["Turns, prompts and tool spans of older sessions are not "
                                                        "backfilled: only token usage is."])
        return self.write(look)

    def written(self, sid: str) -> dict[str, set[str]]:
        """Every content a session wrote, by file (utils/ledger/writes.py).

        Args:
            sid: the session id.

        Returns:
            {real path: the hashes of every content the session gave it}; {} when there is no ledger yet.
        """
        return self.read(lambda con: writes.written(con, sid)) or {}

    def span(self, session: Optional[Callable[[], str]], kind: str, status: str, name: str, attrs: dict[str, Any]) -> None:
        """Keep one span of a run of a harness action.

        Args:
            session: session() -> the calling session's id, or None when the server has no such port.
            kind: the span's kind (tool).
            status: ok or error.
            name: "<block>.<action>".
            attrs: its detail (the names of its arguments).
        """
        def change(con: Any, rec: Any) -> None:
            activity.span(con, session() if session else "", kind, status, name, attrs)
        self.recorded(name, change)
