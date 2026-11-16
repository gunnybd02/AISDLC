"""The MCP server of the harness over stdio, as Claude Code starts it. It only calls assemble; a harness that does not
load writes why on stderr and exits 2."""
from __future__ import annotations

import os
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent.parent  # the code this entry belongs to (a release, or the work tree)
CLAUDE_DIR = Path(os.environ.get("HARNESS_HOME") or CODE_DIR)  # the home: state, config, skills (anchor.py)


def main() -> int:
    """Serve the harness's MCP server over stdio until the input ends.

    Returns:
        The exit code: 0 the input ended, 2 the harness failed (why on stderr).
    """
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")  # bad bytes become U+FFFD, never a crash
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    try:
        sys.path.insert(0, str(CODE_DIR))
        from harness.assemble.engine.live_mcp import serve_live
        serve_live(sys.stdin, sys.stdout, CLAUDE_DIR)
    except BaseException as e:
        sys.stderr.write(f"harness MCP server failed: {type(e).__name__}: {e}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
