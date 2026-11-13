"""size: a .py file has at most 400 lines, a .md file at most 300. A file that does not decode as UTF-8 is reported
here, the one net that reads every .py and .md."""
from nets import files, read

LIMITS = {".py": 400, ".md": 300}


def check(claude_dir):
    out = []
    for rel, path in files(claude_dir, tuple(LIMITS)):
        try:
            lines = len(read(path).splitlines())
        except UnicodeDecodeError as e:
            out.append(f"size: {rel} does not decode as UTF-8 ({e.reason} at byte {e.start})")
            continue
        if lines > LIMITS[path.suffix]:
            out.append(f"size: {rel} has {lines} lines, at most {LIMITS[path.suffix]}")
    return out
