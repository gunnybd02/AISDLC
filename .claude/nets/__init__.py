"""The nets: each module checks one rule over the .claude tree, `check(claude_dir) -> [problem lines]`. The doctor runs
them all; one problem is an ERROR, and there is no list of exceptions."""
from pathlib import Path

SKIP = ("state", "project")  # the private DB; the old harness's trace (project/behaviors.json) until the cutover


def files(claude_dir, suffixes=(), tops=()):
    """(relative posix path, path) of each file of the tree, without caches and the SKIP folders."""
    root = Path(claude_dir)
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        parts = rel.split("/")
        if not path.is_file() or parts[0] in SKIP or "__pycache__" in parts:
            continue
        if (tops and parts[0] not in tops) or (suffixes and path.suffix not in suffixes):
            continue
        yield rel, path
