"""The harness from a terminal, from .claude/: python3 -m entry.cli <door> ... (verify, add file, add test, add
drop-file, add retire-test, behaviors add|list|check). It only calls assemble; exit 1 on a refusal, 2 when the harness
does not load."""
import sys
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parent.parent


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        sys.path.insert(0, str(CLAUDE_DIR))
        from harness.assemble.engine.cli_wire import run_cli
        code, text = run_cli(sys.argv[1:] if argv is None else argv, CLAUDE_DIR)
    except BaseException as e:
        print(f"ERROR the harness does not load: {type(e).__name__}: {e}")
        return 2
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
