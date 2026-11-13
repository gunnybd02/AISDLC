"""imports: mcp and gear import only themselves and utils; utils imports no block; assemble connects them (it loads
mcp and gear through its loader, the one place of a dynamic import, and imports the nets only inside a function, so
they never load on a hook call); entry imports only assemble. It also reports a file that does not parse, for every
net."""
import ast

from nets import files, module_level, read

ALLOWED = {
    "hooks": ("harness.hooks", "harness.utils"),
    "mcp": ("harness.mcp", "harness.utils"),
    "gear": ("harness.gear", "harness.utils"),
    "utils": ("harness.utils",),
    "assemble": ("harness.assemble", "harness.utils", "nets"),
    "entry": ("harness.assemble",),
    "harness": (),
}
INTERNAL = ("harness", "nets", "entry", "tests")
DYNAMIC_OK = ("harness/assemble/loader.py",)


def owner(rel):
    parts = rel.split("/")
    return "entry" if parts[0] == "entry" else (parts[1] if len(parts) > 2 else "harness")


def targets(node, rel):
    """The dotted names an import statement reaches, relative imports resolved from the file's package."""
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    package = rel.split("/")[:-1]
    base = package[:len(package) - node.level + 1] if node.level else []
    base = ".".join(base + ([node.module] if node.module else []))
    return [f"{base}.{a.name}" if base else a.name for a in node.names]


def under(name, prefixes):
    return any(name == p or name.startswith(p + ".") for p in prefixes)


def dynamic(node):
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (isinstance(f, ast.Name) and f.id == "__import__") or (isinstance(f, ast.Attribute) and f.attr == "import_module")


def check(claude_dir):
    out = []
    for rel, path in files(claude_dir, (".py",), ("harness", "entry", "nets")):
        try:
            tree = ast.parse(read(path))
        except UnicodeDecodeError:
            continue  # size_net reports it
        except (SyntaxError, ValueError) as e:
            out.append(f"imports: {rel}:{getattr(e, 'lineno', 0)} does not parse ({getattr(e, 'msg', e)})")
            continue
        if rel.startswith("nets/"):
            continue
        who = owner(rel)
        if who == "assemble":
            for node in module_level(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)) and \
                        any(n.split(".")[0] == "nets" for n in targets(node, rel)):
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
