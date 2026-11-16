"""verdict: only gear/decide/arbiter.py judges. Outside it and utils/contracts.py no code writes a verdict word, names a verdict
constant (ALLOW, ASK, REFUSE) or makes a Verdict; mcp turns a verdict into Claude Code's words through CLAUDE_DECISION.
A type hint may name Verdict (a function that takes or gives one says so), and so may the import it needs: a hint
judges nothing. Making one, Verdict(...), or reading a constant stays the arbiter's."""
import ast
from pathlib import Path

from harness.nets import python

WORDS = ("allow", "ask", "refuse", "deny")
NAMES = ("ALLOW", "ASK", "REFUSE", "Verdict")
OWNERS = ("harness/gear/decide/arbiter.py", "harness/utils/contracts.py")


def hinted(tree: ast.AST) -> set[int]:
    """The ids of the nodes inside a type hint of the tree: a parameter's, a return's, an annotated name's."""
    roots = []
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            roots.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            roots.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            roots.append(node.annotation)
    return {id(n) for root in roots for n in ast.walk(root)}


def judging(node: ast.AST) -> str:
    """What in this node judges, or "": a verdict word as a constant, a verdict name used, or a verdict constant
    imported. Importing the name Verdict alone is no judging (a type hint needs it); using it outside a hint is."""
    if isinstance(node, ast.Constant) and node.value in WORDS:
        return f"writes the verdict '{node.value}'"
    if isinstance(node, ast.Name) and node.id in NAMES:
        return f"uses {node.id}"
    if isinstance(node, ast.Attribute) and node.attr in NAMES:
        return f"uses {node.attr}"
    if isinstance(node, ast.ImportFrom):
        names = [a.name for a in node.names if a.name in NAMES and a.name != "Verdict"]
        return f"imports {', '.join(names)}" if names else ""
    return ""


def check(claude_dir: Path) -> list[str]:
    """Every place outside the owners that judges: "verdict: <file>:<line> <what>; only ... judges"."""
    out = []
    for rel, tree in python(claude_dir, ("harness",)):
        if rel in OWNERS:
            continue
        hints = hinted(tree)
        for node in ast.walk(tree):
            what = "" if id(node) in hints else judging(node)
            if what:
                out.append(f"verdict: {rel}:{node.lineno} {what}; only gear/decide/arbiter.py judges")
    return out
