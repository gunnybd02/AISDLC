"""The nets: each module checks one rule over the .claude tree, `check(claude_dir) -> [problem lines]`. The doctor runs
them all; one problem is an ERROR.

Two places are not read, and only these two: `state/` (the private DB, not in git) and `project/behaviors.json` (the
old harness's record of the tests here, until the cutover)."""
from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path


def skipped(rel: str) -> bool:
    """Whether a file is one no net reads: under state/, project/behaviors.json, or in a __pycache__ folder.

    Args:
        rel: the file's posix path from the .claude folder.

    Returns:
        True when it is left out.
    """
    parts = rel.split("/")
    return parts[0] == "state" or rel == "project/behaviors.json" or "__pycache__" in parts


INSIDE = ("harness/nets", "harness/tests")  # folders inside harness that a net reads only when it names them


def under(rel: str, top: str) -> bool:
    """Whether a path is top or inside it.

    Args:
        rel: a posix path from the .claude folder.
        top: a folder, the same way.

    Returns:
        True when rel is top or under it.
    """
    return rel == top or rel.startswith(top + "/")


def wanted(rel: str, tops: tuple[str, ...]) -> bool:
    """Whether a file is under one of the tops; harness alone leaves out its nets and tests.

    Args:
        rel: the file's posix path from the .claude folder.
        tops: the folders read; harness/nets and harness/tests count only when named.

    Returns:
        True when the file is read.
    """
    return any(under(rel, t) for t in tops) and not any(under(rel, i) and i not in tops for i in INSIDE)


def files(claude_dir: str | Path, suffixes: tuple[str, ...] = (),
          tops: tuple[str, ...] = ()) -> Iterator[tuple[str, Path]]:
    """(relative posix path, path) of each file of the tree that is read (every file, or those under tops).

    Args:
        claude_dir: the .claude folder read.
        suffixes: the suffixes read (".py"...); () for every file.
        tops: the folders read (wanted); () for the whole tree.

    Returns:
        (posix path from claude_dir, path) of each file, sorted.
    """
    root = Path(claude_dir)
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if not path.is_file() or skipped(rel):
            continue
        if (tops and not wanted(rel, tops)) or (suffixes and path.suffix not in suffixes):
            continue
        yield rel, path


def read(path: str | Path) -> str:
    """The text of a file, as UTF-8 (a BOM is dropped).

    Args:
        path: the file.

    Returns:
        Its text.

    Raises:
        UnicodeDecodeError: the file is not UTF-8.
    """
    return Path(path).read_text(encoding="utf-8-sig")


def python(claude_dir: str | Path, tops: tuple[str, ...]) -> Iterator[tuple[str, ast.Module]]:
    """(relative path, syntax tree) of each Python file under tops. A file that does not decode or parse is left out
    here; size_net reports the first, imports_net the second, so each is reported once.

    Args:
        claude_dir: the .claude folder read.
        tops: the folders read (wanted).

    Returns:
        (posix path from claude_dir, its module's syntax tree) of each file that parses.
    """
    for rel, path in files(claude_dir, (".py",), tops):
        try:
            yield rel, ast.parse(read(path))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue


def module_level(tree: ast.Module) -> Iterator[ast.AST]:
    """The nodes that run when the module is imported: everything outside the bodies of functions and lambdas.

    Args:
        tree: the module's syntax tree.

    Returns:
        Each such node (a function's own node, with its decorators and defaults, is one).
    """
    todo = list(tree.body)
    while todo:
        node = todo.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            todo.extend(ast.iter_child_nodes(node))
