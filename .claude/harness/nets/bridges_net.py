"""bridges: no file only passes names on (imports, then __all__ or B2 = B); import from where the code lives."""
from __future__ import annotations

import ast
from pathlib import Path

from harness.nets import python


def is_bridge(tree: ast.Module) -> bool:
    """Whether a module only passes names on: after its docstring, only imports, __all__ and aliases of imported names.

    Args:
        tree: the module's syntax tree.

    Returns:
        True when it imports something and does nothing else.
    """
    body = tree.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    imported = set()
    for node in body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported |= {a.asname or a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.Assign) and [ast.unparse(t) for t in node.targets] == ["__all__"]:
            continue
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
              and isinstance(node.value, ast.Name) and node.value.id in imported):
            imported.add(node.targets[0].id)
        else:
            return False
    return bool(imported)


def check(claude_dir: Path) -> list[str]:
    """Every module of harness/ (with its nets) that only passes names on.

    Args:
        claude_dir: the .claude folder read.

    Returns:
        "bridges: <file> only passes names on; ..." lines.
    """
    return [f"bridges: {rel} only passes names on; import them from where they live"
            for rel, tree in python(claude_dir, ("harness", "harness/nets")) if is_bridge(tree)]
