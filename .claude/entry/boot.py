"""Boot: what Claude Code runs (settings.json and .mcp.json name this file): python3 .claude/entry/boot.py <entry>
[args], entry one of hook, mcp_server, doctor, cli. It runs that entry of the release in force (state/live/current),
never the work tree a session edits; with no release yet, the work tree's own. The entry is told the home (the real
.claude folder: state, config, skills) and the code it runs (HARNESS_HOME, HARNESS_CODE). Any failure exits 2, which
blocks a hook's call. Standard library only: this file is the trust anchor, and no session may write it."""
import os
import runpy
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parent.parent
ENTRIES = ("hook", "mcp_server", "doctor", "cli")


def code_dir(home):
    """The release in force, or the home itself when none is published."""
    try:
        sha = (home / "state" / "live" / "current").read_text(encoding="utf-8").strip()
    except OSError:
        return home
    release = home / "state" / "live" / sha
    return release if sha and (release / "harness").is_dir() else home


def main():
    try:
        name = sys.argv[1] if len(sys.argv) > 1 else ""
        if name not in ENTRIES:
            sys.stderr.write(f"boot: the entry is one of {', '.join(ENTRIES)}\n")
            return 2
        code = code_dir(HOME)
        os.environ["HARNESS_HOME"], os.environ["HARNESS_CODE"] = str(HOME), str(code)
        sys.argv = [str(code / "entry" / f"{name}.py")] + sys.argv[2:]
        runpy.run_path(sys.argv[0], run_name="__main__")
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 2)
    except BaseException as e:
        sys.stderr.write(f"boot failed, the call is blocked: {type(e).__name__}: {e}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
