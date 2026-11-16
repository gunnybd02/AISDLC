"""Claude Code SessionStart hook (installed by harness/entry/install.py): when a session begins, bring the harness to
the newest main of its clone and put it in force when its doctor is clean (assemble/engine/cli_live.py session_update). A cloud
machine is prepared ahead of time, so the setup script's harness can be hours old by then. It never blocks: whatever
fails, the session starts on the harness it has and reads why. The start is recorded in the ledger: the session's row,
and a higher epoch after a compact or clear (docs/12-ledger.md). A session cannot run it itself (agent.session_start)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent.parent  # the code this entry belongs to (a release, or the work tree)
CLAUDE_DIR = Path(os.environ.get("HARNESS_HOME") or CODE_DIR)  # the home: state, config, skills (anchor.py)


def main() -> int:
    """Bring the harness up to date as a session starts and tell the session what runs (on stdout, as hook JSON).

    Returns:
        0, always: a session start is never blocked.
    """
    try:
        payload = sys.stdin.read()  # the hook payload: the session and why it starts (startup, resume, clear, compact)
        sys.path.insert(0, str(CODE_DIR))
        from harness.assemble.engine.cli_live import session_began, session_update
        session_began(CLAUDE_DIR, payload)  # recorded by the code that runs now, before a newer one is put in force
        text = session_update(CLAUDE_DIR)
    except BaseException as e:
        text = f"The harness was not brought up to date at session start: {type(e).__name__}: {e}"
    out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}
    sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
