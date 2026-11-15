"""entry: an entry script (harness/entry/*.py, the forwarders of entry/, and anchor.py beside .claude) imports only the
standard library at load time, wherever the import sits (inside try, if, with...), and its main() has a handler for
BaseException. So a harness that does not load, or quits, is still answered: the hook exits 2 and blocks the call
instead of crashing open."""
import ast
import sys
from pathlib import Path

from nets import module_level, python, read

STDLIB = set(sys.stdlib_module_names) | {"__future__"}


def imported(node):
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom):
        return ["."] if node.level else [node.module or "."]
    return []


def catches_everything(tree):
    """main() holds, in its own body, a try with a handler for BaseException (not one in a nested function)."""
    main = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    return main is not None and any(
        isinstance(n, ast.Try) and any(isinstance(h.type, ast.Name) and h.type.id == "BaseException" for h in n.handlers)
        for n in main.body)


def scripts(claude_dir):
    """(name, syntax tree) of each entry script: harness/entry/, entry/, and the anchor when it is beside the tree."""
    for rel, tree in python(claude_dir, ("entry", "harness")):
        if rel.startswith(("entry/", "harness/entry/")):
            yield rel, tree
    anchor = Path(claude_dir).resolve().parent / "anchor.py"
    if Path(claude_dir).name == ".claude" and anchor.is_file():
        try:
            yield "../anchor.py", ast.parse(read(anchor))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            yield "../anchor.py", ast.parse("")


def check(claude_dir):
    out = []
    for rel, tree in scripts(claude_dir):
        for node in module_level(tree):
            for name in imported(node):
                if name.split(".")[0] not in STDLIB:
                    out.append(f"entry: {rel}:{node.lineno} imports {name} at load time; import the harness inside main()")
        if not catches_everything(tree):
            out.append(f"entry: {rel} has no main() with a handler for BaseException")
    return out
