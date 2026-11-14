"""Install the harness for every Claude Code session of this user: python3 .claude/entry/install.py [--uninstall]
[--user-dir DIR] [--claude-json FILE] [--python EXE] [--no-cli]. It only calls assemble (cli_install.py); exit 1 when
it cannot, 2 when the harness does not load."""
import argparse
import sys
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parent.parent


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        sys.path.insert(0, str(CLAUDE_DIR))
        from harness.assemble.engine.cli_install import install, uninstall
        parser = argparse.ArgumentParser(prog="install.py")
        parser.add_argument("--uninstall", action="store_true")
        parser.add_argument("--user-dir", default=str(Path.home() / ".claude"))
        parser.add_argument("--claude-json", default=str(Path.home() / ".claude.json"))
        parser.add_argument("--python", default=sys.executable or "python3")
        parser.add_argument("--no-cli", action="store_true")
        args = parser.parse_args(argv)
        if args.uninstall:
            print(uninstall(CLAUDE_DIR, args.user_dir, args.claude_json, not args.no_cli))
        else:
            print(install(CLAUDE_DIR, args.user_dir, args.claude_json, args.python, not args.no_cli))
    except ValueError as e:
        print(f"refused: {e}")
        return 1
    except BaseException as e:
        print(f"ERROR the harness does not load: {type(e).__name__}: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
