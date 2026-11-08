"""End to end: the entry scripts run as Claude Code runs them, in a process of their own."""
import shutil
import subprocess
import sys

from tests import CLAUDE_DIR, tree


def copy_tree(test, extra=None):
    """A copy of the real tree (code and config) in a temp folder, with {relative path: text} written over it."""
    root = tree(test, {})
    for name in ("harness", "entry", "nets", "skills"):
        if (CLAUDE_DIR / name).is_dir():
            shutil.copytree(CLAUDE_DIR / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(CLAUDE_DIR / "project.json", root / "project.json")
    for rel, text in (extra or {}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def run(script, stdin="", args=()):
    """Run an entry script with the given stdin; return (exit code, stdout, stderr)."""
    p = subprocess.run([sys.executable, str(script), *args], input=stdin.encode("utf-8"), capture_output=True,
                       timeout=60)
    return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")
