"""The health of the harness: every problem of the tree as an ERROR line, then the count. Exit 1 when there is one,
2 when the harness does not even load."""
import sys
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parent.parent


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        sys.path.insert(0, str(CLAUDE_DIR))
        from harness.assemble.build import doctor, report
        problems = doctor()
    except Exception as e:
        print(f"ERROR the harness does not load: {type(e).__name__}: {e}")
        return 2
    print(report(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
