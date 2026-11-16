"""imports: mcp and gear import only themselves and utils; utils imports no block; assemble connects them (it loads
mcp and gear through its loader, the one place of a dynamic import, and imports the nets only inside a function, so
they never load on a hook call); an entry (harness/entry/) imports only assemble. It also reports a file that does not parse, for every
net."""
from __future__ import annotations

import ast
from pathlib import Path

from harness.nets import files, module_level, read

ALLOWED = {
    "hooks": ("harness.hooks", "harness.utils"),
    "mcp": ("harness.mcp", "harness.utils"),
    "gear": ("harness.gear", "harness.utils"),
    "utils": ("harness.utils",),
    "assemble": ("harness.assemble", "harness.utils", "harness.nets"),
    "entry": ("harness.assemble",),
    "harness": (),
}
INTERNAL = ("harness", "entry")
DYNAMIC_OK = ("harness/assemble/engine/loader.py", "harness/assemble/engine/live_mcp.py")


def owner(rel: str) -> str:
    """The block a file belongs to, for the import rules.

    Args:
        rel: the file's posix path from the .claude folder.

    Returns:
        "entry" (harness/entry/), the block's folder under harness/, or "harness" for a file right in it.
    """
    parts = rel.split("/")
    return "entry" if parts[:2] == ["harness", "entry"] else (parts[1] if len(parts) > 2 else "harness")


def targets(node: ast.Import | ast.ImportFrom, rel: str) -> list[str]:
    """The dotted names an import statement reaches, relative imports resolved from the file's package.

    Args:
        node: the import statement.
        rel: the importing file's posix path from the .claude folder.

    Returns:
        The full dotted name of each name imported.
    """
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    package = rel.split("/")[:-1]
    base = package[:len(package) - node.level + 1] if node.level else []
    base = ".".join(base + ([node.module] if node.module else []))
    return [f"{base}.{a.name}" if base else a.name for a in node.names]


def under(name: str, prefixes: tuple[str, ...]) -> bool:
    """Whether a dotted name is one of the prefixes or inside one.

    Args:
        name: a dotted module name.
        prefixes: dotted package names.

    Returns:
        True when name is a prefix or starts with one and a dot.
    """
    return any(name == p or name.startswith(p + ".") for p in prefixes)


def dynamic(node: ast.AST) -> bool:
    """Whether a node is a dynamic import: a call of __import__ or of an import_module.

    Args:
        node: a syntax node.

    Returns:
        True when it is such a call.
    """
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (isinstance(f, ast.Name) and f.id == "__import__") or (isinstance(f, ast.Attribute) and f.attr == "import_module")


def check(claude_dir: Path) -> list[str]:
    """Every import that breaks the connection rule (ALLOWED), a dynamic import outside DYNAMIC_OK, assemble importing
    the nets at load time, and a file of harness/ that does not parse.

    Args:
        claude_dir: the .claude folder read.

    Returns:
        "imports: <file>:<line> ..." lines.
    """
    out = []
    for rel, path in files(claude_dir, (".py",), ("harness", "harness/nets")):
        try:
            tree = ast.parse(read(path))
        except UnicodeDecodeError:
            continue  # size_net reports it
        except (SyntaxError, ValueError) as e:
            out.append(f"imports: {rel}:{getattr(e, 'lineno', 0)} does not parse ({getattr(e, 'msg', e)})")
            continue
        if rel.startswith("harness/nets/"):
            continue
        who = owner(rel)
        if who == "assemble":
            for node in module_level(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)) and \
                        any(under(n, ("harness.nets",)) for n in targets(node, rel)):
                    out.append(f"imports: {rel}:{node.lineno} imports the nets at load time; import them inside a function")
        for node in ast.walk(tree):
            names = targets(node, rel) if isinstance(node, (ast.Import, ast.ImportFrom)) else []
            for name in names:
                if name.split(".")[0] in INTERNAL and not under(name, ALLOWED.get(who, ())):
                    out.append(f"imports: {rel}:{node.lineno} imports {name}; {who} may import only "
                               f"{', '.join(ALLOWED.get(who, ())) or 'nothing of the harness'}")
            if rel not in DYNAMIC_OK and (dynamic(node) or any(n.split(".")[0] == "importlib" for n in names)):
                out.append(f"imports: {rel}:{node.lineno} is a dynamic import; only assemble/loader.py loads by name")
    return out
