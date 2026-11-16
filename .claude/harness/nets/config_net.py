"""config: project.json, the values of the user, is named only in assemble/config.py, its one reader."""
from __future__ import annotations

import ast
from pathlib import Path

from harness.nets import python

DOOR = "harness/assemble/engine/config.py"


def docstrings(tree: ast.Module) -> set[int]:
    """The ids of the docstring nodes of a module and of its functions and classes (a docstring may name the file).

    Args:
        tree: the module's syntax tree.

    Returns:
        The id() of each docstring's Constant node.
    """
    nodes = [tree] + [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    return {id(n.body[0].value) for n in nodes
            if n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}


def check(claude_dir: Path) -> list[str]:
    """Every string of harness/ and entry/ but config.py, docstrings aside, that names project.json.

    Args:
        claude_dir: the .claude folder read.

    Returns:
        "config: <file>:<line> names project.json; ..." lines.
    """
    out = []
    for rel, tree in python(claude_dir, ("harness", "entry")):
        if rel == DOOR:
            continue
        skip = docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip \
                    and "project.json" in node.value:
                out.append(f"config: {rel}:{node.lineno} names project.json; read it through {DOOR}")
    return out
