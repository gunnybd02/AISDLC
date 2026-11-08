"""Claude Code hook: the event JSON on stdin, the answer on stdout. Any failure exits 2, which blocks the tool call.
Only the standard library is imported at the top, so a harness that does not even import still exits 2."""
import sys
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parent.parent


def main():
    try:
        sys.path.insert(0, str(CLAUDE_DIR))
        from harness.assemble.build import run_hook
        answer = run_hook(sys.stdin.buffer.read().decode("utf-8"))
    except Exception as e:
        sys.stderr.write(f"harness hook failed, the call is blocked: {type(e).__name__}: {e}\n")
        return 2
    sys.stdout.buffer.write(answer.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
