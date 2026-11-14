"""What a commit would add: the added lines of each file to commit, against HEAD (a new file: all its lines). The
secret scan reads these, never the whole history."""
import os

from harness.utils.git.run import GitError, git

LONGEST = 2_000_000  # characters read of one new file


def added_lines(repo, paths):
    """{path from the repository root: [added lines]} of paths, against HEAD; a binary file adds no line."""
    out = {p: [] for p in paths}
    try:
        diff = git(repo, "diff", "HEAD", "--no-color", "--no-renames", "--unified=0", "--", *paths) if paths else ""
    except GitError:
        diff = ""
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif current is not None and line.startswith("+") and not line.startswith("+++"):
            out.setdefault(current, []).append(line[1:])
    for p in paths:
        if not out.get(p) and os.path.isfile(os.path.join(repo, p)):
            try:
                tracked = git(repo, "ls-files", "--", p).strip()
            except GitError:
                tracked = ""
            if not tracked:
                try:
                    with open(os.path.join(repo, p), encoding="utf-8") as f:
                        out[p] = f.read(LONGEST).splitlines()
                except (OSError, UnicodeDecodeError):
                    out[p] = []
    return out
