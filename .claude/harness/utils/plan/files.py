"""The files a plan names, and paths as the gates compare them: real paths (8.3 short names expanded), no \\\\?\\
prefix, case folded where the system folds it."""
import os

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
