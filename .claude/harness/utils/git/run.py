"""git: every git command of the harness. Arguments are a list, never a shell string; each run has a timeout; the
GIT_* variables a caller may leave behind (GIT_DIR, GIT_INDEX_FILE...) are taken out, so the repository given is the
one read."""
import os
import subprocess

TIMEOUT = 30


class GitError(RuntimeError):
    pass


def env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(repo, *args, timeout=TIMEOUT, binary=False):
    """The output of `git -C repo args`; a failure raises GitError with git's own words."""
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=timeout, env=env())
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitError(f"git {' '.join(args)}: {e}") from e
    if p.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {p.stderr.decode('utf-8', 'replace').strip()}")
    return p.stdout if binary else p.stdout.decode("utf-8", "replace")
