"""verdict: only gear/decide.py judges. Outside it and utils/contracts.py no code writes a verdict word, names a verdict
constant (ALLOW, ASK, REFUSE) or makes a Verdict; mcp turns a verdict into Claude Code's words through CLAUDE_DECISION."""
import ast

from nets import python

WORDS = ("allow", "ask", "refuse", "deny")
NAMES = ("ALLOW", "ASK", "REFUSE", "Verdict")
OWNERS = ("harness/gear/decide.py", "harness/utils/contracts.py")


def judging(node):
    """What in this node judges, or ""."""
    if isinstance(node, ast.Constant) and node.value in WORDS:
        return f"writes the verdict '{node.value}'"
    if isinstance(node, ast.Name) and node.id in NAMES:
        return f"uses {node.id}"
    if isinstance(node, ast.Attribute) and node.attr in NAMES:
        return f"uses {node.attr}"
    if isinstance(node, ast.ImportFrom):
        names = [a.name for a in node.names if a.name in NAMES]
        return f"imports {', '.join(names)}" if names else ""
    return ""


def check(claude_dir):
    out = []
    for rel, tree in python(claude_dir, ("harness", "entry")):
        if rel in OWNERS:
            continue
        for node in ast.walk(tree):
            what = judging(node)
            if what:
                out.append(f"verdict: {rel}:{node.lineno} {what}; only gear/decide.py judges")
    return out
