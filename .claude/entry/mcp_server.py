"""The MCP server of the harness over stdio, as Claude Code starts it. It only calls assemble; a harness that does not
load writes why on stderr and exits 2."""
import sys
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parent.parent


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    try:
        sys.path.insert(0, str(CLAUDE_DIR))
        from harness.assemble.build import run_mcp
        run_mcp(sys.stdin, sys.stdout)
    except Exception as e:
        sys.stderr.write(f"harness MCP server failed: {type(e).__name__}: {e}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
