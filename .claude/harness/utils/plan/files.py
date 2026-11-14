"""The files a plan names, and paths as the gates compare them: real paths (8.3 short names expanded), no \\\\?\\
prefix, case folded where the system folds it."""
import os
import re

PREFIXES = ("\\\\?\\", "//?/", "\\\\.\\", "//./")


def resolved(path):
    path = str(path)
    for prefix in PREFIXES:
        if path.startswith(prefix):
            path = path[len(prefix):]
    return os.path.realpath(path)


def key(path):
    return os.path.normcase(resolved(path))


def rel_key(path):
    """A path from a plan's root as the gates compare it."""
    return os.path.normcase(os.path.normpath(path))


def named(plan):
    return {rel_key(p) for p in plan["files"] + plan["tests"]}


def relative(path, root):
    """path from root, or None when path is not under root."""
    try:
        rel = os.path.relpath(key(path), key(root))
    except ValueError:  # another drive
        return None
    return None if rel == os.pardir or rel.startswith(os.pardir + os.sep) else rel


WILD = set("*?")


def is_pattern(path):
    return bool(WILD & set(path)) or path.endswith("/")


def pattern_re(pattern):
    """A plan path as a regex of paths from the root: ** any run (/ too), * no /, ? one character, a trailing / a
    folder and everything below it."""
    p = pattern.replace("\\", "/").strip("/") if pattern.endswith("/") else pattern.replace("\\", "/")
    out, i = "", 0
    while i < len(p):
        if p.startswith("**", i):
            out += ".*"
            i += 2
            if p.startswith("/", i):
                out += "(?:/)?"
                i += 1
        elif p[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif p[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(p[i]), i + 1
    return re.compile(f"^{out}(/.*)?$" if pattern.endswith("/") else f"^{out}$",
                      re.I if os.path.normcase("A") == "a" else 0)


def matches(patterns, rel):
    rel = rel_key(rel).replace("\\", "/")
    return any(pattern_re(rel_key(p).replace("\\", "/") if not is_pattern(p) else p).match(rel) for p in patterns)


def allows(plan, rel):
    """Whether the plan allows the path rel (from its root): the newest grant of that path decides (add allows, drop
    refuses), else a pattern of its files and tests matches."""
    for op, path in reversed(plan.get("grants", [])):
        if rel_key(path) == rel_key(rel):
            return op == "add"
    return matches(plan.get("files", []) + plan.get("tests", []), rel)


def holds(plan, rel):
    """Whether rel is a folder above a planned file (a mkdir of it is no write of a file): above a named file, above the
    fixed part of a pattern, or under a ** of one."""
    folder = rel_key(rel).replace("\\", "/").rstrip("/")
    for p in plan.get("files", []) + plan.get("tests", []):
        p = p.replace("\\", "/")
        if not is_pattern(p):
            if rel_key(p).replace("\\", "/").startswith(folder + "/"):
                return True
            continue
        head = re.split(r"[*?]", p, 1)[0]  # the fixed part: src/ of src/**/*.py, docs/ of docs/
        base = head.rsplit("/", 1)[0] if "/" in head else ""
        if (base + "/").startswith(folder + "/") or ("**" in p and folder.startswith(base + "/")):
            return True
    return False
