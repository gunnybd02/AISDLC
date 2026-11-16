"""hints: every function of the harness says what it takes and gives. Each parameter (but the self or cls of a method)
and each return has a type hint, *args and **kwargs too; each function at module level and each method has a
docstring. A function nested in another (a closure such as change(con, rec)) needs its hints only: the function
around it documents it. The code read is harness/ with its nets (not its tests), the forwarders of entry/ and the
anchor.

The data the hints name are in harness/utils/shapes.py (PlanItems, ApprovedPlan, Ticket, Receipt, PlanStore...)."""
import ast
from collections.abc import Iterator
from pathlib import Path

from harness.nets import python, read

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def functions(tree: ast.AST) -> Iterator[tuple[ast.FunctionDef, bool, bool]]:
    """(function, is_method, is_nested) of each function of the tree, outermost first."""
    todo = [(node, False, False) for node in getattr(tree, "body", [])]
    while todo:
        node, in_class, in_function = todo.pop(0)
        if isinstance(node, FUNCTIONS):
            yield node, in_class, in_function
            todo.extend((child, False, True) for child in node.body)
        elif isinstance(node, ast.ClassDef):
            todo.extend((child, True, in_function) for child in node.body)
        else:
            todo.extend((child, in_class, in_function) for child in ast.iter_child_nodes(node)
                        if isinstance(child, (ast.stmt, ast.excepthandler)))


def missing(node: ast.FunctionDef, is_method: bool) -> list[str]:
    """The parameters of node without a hint ("return" for the return), the self or cls of a method left out."""
    args = node.args
    plain = args.posonlyargs + args.args
    static = any(isinstance(d, ast.Name) and d.id == "staticmethod" for d in node.decorator_list)
    if is_method and not static and plain:
        plain = plain[1:]
    out = [a.arg for a in plain + args.kwonlyargs if a.annotation is None]
    out += [f"*{a.arg}" for a in (args.vararg,) if a is not None and a.annotation is None]
    out += [f"**{a.arg}" for a in (args.kwarg,) if a is not None and a.annotation is None]
    return out + (["return"] if node.returns is None else [])


def problems(rel: str, tree: ast.AST) -> list[str]:
    """The problems of one file: "hints: <file>:<line> <function> has no hint for a, return" and "... has no
    docstring"."""
    out = []
    for node, is_method, is_nested in functions(tree):
        gaps = missing(node, is_method)
        if gaps:
            out.append(f"hints: {rel}:{node.lineno} {node.name} has no hint for {', '.join(gaps)}")
        if not is_nested and not ast.get_docstring(node):
            out.append(f"hints: {rel}:{node.lineno} {node.name} has no docstring")
    return out


def check(claude_dir: Path) -> list[str]:
    """Every function of harness/ (tests left out), entry/ and the anchor beside the tree without full hints or, at
    module level and in a class, without a docstring."""
    out = []
    for rel, tree in python(claude_dir, ("harness", "harness/nets", "entry")):
        out += problems(rel, tree)
    anchor = Path(claude_dir).resolve().parent / "anchor.py"
    if Path(claude_dir).name == ".claude" and anchor.is_file():
        try:
            out += problems("../anchor.py", ast.parse(read(anchor)))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            pass  # imports_net and size_net report a file that does not read
    return out
