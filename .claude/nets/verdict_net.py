"""verdict: the verdict words are written only in gear/decide.py and utils/contracts.py; everywhere else the code uses
the constants, so no block can judge on its own."""
import ast

from nets import files

WORDS = ("allow", "ask", "refuse", "deny")
OWNERS = ("harness/gear/decide.py", "harness/utils/contracts.py")


def check(claude_dir):
    out = []
    for rel, path in files(claude_dir, (".py",), ("harness", "entry")):
        if rel in OWNERS:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and node.value in WORDS:
                out.append(f"verdict: {rel}:{node.lineno} writes the verdict '{node.value}'; only decide judges")
    return out
