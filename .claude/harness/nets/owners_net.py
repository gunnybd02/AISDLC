"""owners: one owner per concept (docs/13-cloud-foundation.md). Three faults come back when nothing watches them:
- the same function body in two places (a copy instead of an import), read in harness/ but its tests and nets;
- an MCP action that looks a port up (ctx.ports.get(...)): a looked-up port escapes the doctor's needed-port check, so
  an action declares every port it reads in needs and reads it as ctx.ports[name];
- a text that tells the model run('block', 'action') for an action that does not exist (a renamed or a dropped one).
A body is compared without its docstring, and only when it is longer than SHORT characters of syntax: a one-line
return of a field is no copy worth a home."""
from __future__ import annotations

import ast
import re
from pathlib import Path

from harness.nets import files, read

SHORT = 120  # characters of ast.dump below which a body is too small to be a copy
ACTIONS_DIR = "harness/mcp/actions"
NAMED = re.compile(r"run\('([a-z_]+)', '([a-z_]+)'")


def body_key(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """The syntax of a function's body without its docstring, as one comparable text.

    Args:
        node: the function.

    Returns:
        ast.dump of the body; "" when it is shorter than SHORT.
    """
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    key = ast.dump(ast.Module(body=body, type_ignores=[]))
    return key if len(key) > SHORT else ""


def actions(trees: dict[str, ast.Module]) -> set[str]:
    """The names of the MCP actions, read from the ACTIONS lists of mcp/actions/*.py.

    Args:
        trees: the parsed files by their posix path.

    Returns:
        {"block.name", ...}.
    """
    out = set()
    for rel, tree in trees.items():
        if not rel.startswith(ACTIONS_DIR + "/"):
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "ACTIONS" for t in node.targets) \
                    and isinstance(node.value, ast.List):
                out |= {e.elts[0].value for e in node.value.elts
                        if isinstance(e, ast.Tuple) and e.elts and isinstance(e.elts[0], ast.Constant)}
    return out


def looked_up(tree: ast.Module) -> list[int]:
    """The lines of a file where a port is looked up: <anything>.ports.get(...).

    Args:
        tree: the parsed file.

    Returns:
        The line numbers.
    """
    return [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get" and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "ports"]


def check(claude_dir: Path) -> list[str]:
    """Every copied function body, every looked-up port of an action, and every next step naming no action.

    Args:
        claude_dir: the .claude folder read.

    Returns:
        "owners: ..." lines.
    """
    trees = {}
    for rel, path in files(claude_dir, (".py",), ("harness",)):
        try:
            trees[rel] = ast.parse(read(path))
        except (SyntaxError, ValueError, UnicodeDecodeError):
            continue  # imports_net and size_net report it
    out, seen = [], {}
    for rel, tree in sorted(trees.items()):
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                key = body_key(node)
                if not key:
                    continue
                here = f"{rel}:{node.lineno} {node.name}"
                if key in seen:
                    out.append(f"owners: {here} is a copy of {seen[key]}; import the one owner instead")
                else:
                    seen[key] = here
        if rel.startswith(ACTIONS_DIR + "/"):
            out += [f"owners: {rel}:{n} looks a port up (ports.get); declare it in needs and read ctx.ports[name]"
                    for n in looked_up(tree)]
    known = actions(trees)
    for rel, tree in sorted(trees.items()):
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for m in NAMED.finditer(node.value):
                    if f"{m.group(1)}.{m.group(2)}" not in known:
                        out.append(f"owners: {rel}:{node.lineno} tells the model run('{m.group(1)}', "
                                   f"'{m.group(2)}'), which is no action")
    return out
