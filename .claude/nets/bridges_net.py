"""bridges: no file only passes names on (imports, then __all__ or B2 = B); import from where the code lives."""
import ast

from nets import files


def is_bridge(tree):
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


def check(claude_dir):
    return [f"bridges: {rel} only passes names on; import them from where they live"
            for rel, path in files(claude_dir, (".py",), ("harness", "entry", "nets"))
            if is_bridge(ast.parse(path.read_text(encoding="utf-8")))]
