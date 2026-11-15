"""Forwarder, kept for machines set up before anchor.py: their hooks and MCP server name .claude/entry/boot.py. It runs
anchor.py at the repository root with the same arguments. Standard library only; whatever fails exits 2.
Removed once no installed machine names this path."""
import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent.parent / "anchor.py"


def main():
    try:
        sys.argv = [str(TARGET)] + sys.argv[1:]
        runpy.run_path(str(TARGET), run_name="__main__")
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 2)
    except BaseException as e:
        sys.stderr.write(f"boot forwarder failed, the call is blocked: {type(e).__name__}: {e}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
