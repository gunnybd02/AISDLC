"""config: project.json, the values of the user, is named only in assemble/config.py, its one reader."""
import ast

from nets import files

DOOR = "harness/assemble/config.py"


def docstrings(tree):
    nodes = [tree] + [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    return {id(n.body[0].value) for n in nodes
            if n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}


def check(claude_dir):
    out = []
    for rel, path in files(claude_dir, (".py",), ("harness", "entry")):
        if rel == DOOR:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip \
                    and "project.json" in node.value:
                out.append(f"config: {rel}:{node.lineno} names project.json; read it through {DOOR}")
    return out
