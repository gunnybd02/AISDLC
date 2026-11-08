"""size: a .py file has at most 500 lines, a .md file at most 300."""
from nets import files

LIMITS = {".py": 500, ".md": 300}


def check(claude_dir):
    out = []
    for rel, path in files(claude_dir, tuple(LIMITS)):
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > LIMITS[path.suffix]:
            out.append(f"size: {rel} has {lines} lines, at most {LIMITS[path.suffix]}")
    return out
