"""The health of the harness: every problem of the tree as an ERROR line, then the count. Exit 1 when there is one,
2 when the harness does not even load."""
import os
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent  # the code this entry belongs to (a release, or the work tree)
CLAUDE_DIR = Path(os.environ.get("HARNESS_HOME") or CODE_DIR)  # the home: state, config, skills (entry/boot.py)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        sys.path.insert(0, str(CODE_DIR))
        from harness.assemble.engine.checks import doctor, report
        problems = doctor(CLAUDE_DIR)
    except BaseException as e:
        print(f"ERROR the harness does not load: {type(e).__name__}: {e}")
        return 2
    print(report(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
