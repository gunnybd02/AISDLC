"""The nets: each module checks one rule over the .claude tree, `check(claude_dir) -> [problem lines]`. The doctor runs
them all; one problem is an ERROR.

Two places are not read, and only these two: `state/` (the private DB, not in git) and `project/behaviors.json` (the
old harness's record of the tests here, until the cutover)."""
import ast
from pathlib import Path


def skipped(rel):
    parts = rel.split("/")
    return parts[0] == "state" or rel == "project/behaviors.json" or "__pycache__" in parts


def files(claude_dir, suffixes=(), tops=()):
    """(relative posix path, path) of each file of the tree that is read."""
    root = Path(claude_dir)
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if not path.is_file() or skipped(rel):
            continue
        if (tops and rel.split("/")[0] not in tops) or (suffixes and path.suffix not in suffixes):
            continue
        yield rel, path


def read(path):
    return Path(path).read_text(encoding="utf-8-sig")


def python(claude_dir, tops):
    """(relative path, syntax tree) of each Python file under tops. A file that does not decode or parse is left out
    here; size_net reports the first, imports_net the second, so each is reported once."""
    for rel, path in files(claude_dir, (".py",), tops):
        try:
            yield rel, ast.parse(read(path))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue


def module_level(tree):
    """The nodes that run when the module is imported: everything outside the bodies of functions and lambdas."""
    todo = list(tree.body)
    while todo:
        node = todo.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            todo.extend(ast.iter_child_nodes(node))
