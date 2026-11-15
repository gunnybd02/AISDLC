"""Claude Code SessionStart hook (installed by entry/install.py): when a session begins, bring the harness to the newest
main of its clone and put it in force when its doctor is clean (assemble/engine/cli_live.py session_update). A cloud
machine is prepared ahead of time, so the setup script's harness can be hours old by then. It never blocks: whatever
fails, the session starts on the harness it has and reads why. A session cannot run it itself (agent.session_start)."""
import json
import os
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent  # the code this entry belongs to (a release, or the work tree)
CLAUDE_DIR = Path(os.environ.get("HARNESS_HOME") or CODE_DIR)  # the home: state, config, skills (entry/boot.py)


def main():
    try:
        sys.stdin.read()  # the hook payload: nothing in it changes what is done
        sys.path.insert(0, str(CODE_DIR))
        from harness.assemble.engine.cli_live import session_update
        text = session_update(CLAUDE_DIR)
    except BaseException as e:
        text = f"The harness was not brought up to date at session start: {type(e).__name__}: {e}"
    out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}
    sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
