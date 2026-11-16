"""entry: an entry script (harness/entry/*.py, the forwarders of entry/, and anchor.py beside .claude) imports only the
standard library at load time, wherever the import sits (inside try, if, with...), and its main() has a handler for
BaseException. So a harness that does not load, or quits, is still answered: the hook exits 2 and blocks the call
instead of crashing open."""
from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from pathlib import Path

from harness.nets import module_level, python, read

STDLIB = set(sys.stdlib_module_names) | {"__future__"}


def imported(node: ast.AST) -> list[str]:
    """The modules an import statement names ("." for a relative import); [] for any other node.

    Args:
        node: a syntax node.

    Returns:
        The dotted names imported.
    """
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom):
        return ["."] if node.level else [node.module or "."]
    return []


def catches_everything(tree: ast.Module) -> bool:
    """main() holds, in its own body, a try with a handler for BaseException (not one in a nested function).

    Args:
        tree: the script's syntax tree.

    Returns:
        True when it does.
    """
    main = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    return main is not None and any(
        isinstance(n, ast.Try) and any(isinstance(h.type, ast.Name) and h.type.id == "BaseException" for h in n.handlers)
        for n in main.body)


def scripts(claude_dir: str | Path) -> Iterator[tuple[str, ast.Module]]:
    """(name, syntax tree) of each entry script: harness/entry/, entry/, and the anchor when it is beside the tree.

    Args:
        claude_dir: the .claude folder read.

    Returns:
        (posix path from claude_dir, or ../anchor.py, its syntax tree); an anchor that does not parse gives an empty
        tree.
    """
    for rel, tree in python(claude_dir, ("entry", "harness")):
        if rel.startswith(("entry/", "harness/entry/")):
            yield rel, tree
    anchor = Path(claude_dir).resolve().parent / "anchor.py"
    if Path(claude_dir).name == ".claude" and anchor.is_file():
        try:
            yield "../anchor.py", ast.parse(read(anchor))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            yield "../anchor.py", ast.parse("")


def check(claude_dir: Path) -> list[str]:
    """Every entry script that imports more than the standard library at load time, or whose main() has no handler
    for BaseException.

    Args:
        claude_dir: the .claude folder read.

    Returns:
        "entry: <file>:<line> imports <name> at load time; ..." and "entry: <file> has no main() ..." lines.
    """
    out = []
    for rel, tree in scripts(claude_dir):
        for node in module_level(tree):
            for name in imported(node):
                if name.split(".")[0] not in STDLIB:
                    out.append(f"entry: {rel}:{node.lineno} imports {name} at load time; import the harness inside main()")
        if not catches_everything(tree):
            out.append(f"entry: {rel} has no main() with a handler for BaseException")
    return out
