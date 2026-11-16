"""git: every git command of the harness. Arguments are a list, never a shell string; each run has a timeout; the
GIT_* variables a caller may leave behind (GIT_DIR, GIT_INDEX_FILE...) are taken out, so the repository given is the
one read."""
from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

TIMEOUT = 30


class GitError(RuntimeError):
    """A git command failed or could not run; the message holds the command and git's own words."""


def env() -> dict[str, str]:
    """The environment git runs with.

    Returns:
        A copy of os.environ without the GIT_* variables.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(repo: str | Path, *args: str, timeout: float = TIMEOUT, binary: bool = False) -> str | bytes:
    """The output of `git -C repo args`; a failure raises GitError with git's own words.

    Args:
        repo: the folder git runs in (-C).
        *args: the words after `git -C repo`.
        timeout: the seconds the command may take.
        binary: True to get stdout as bytes.

    Returns:
        stdout: text (UTF-8, bad bytes replaced), or bytes when binary.

    Raises:
        GitError: git cannot start, times out or exits non-zero.
    """
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=timeout, env=env())
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitError(f"git {' '.join(args)}: {e}") from e
    if p.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {p.stderr.decode('utf-8', 'replace').strip()}")
    return p.stdout if binary else p.stdout.decode("utf-8", "replace")


def run_git(repo: str | Path, words: Sequence[str], timeout: float = 120) -> tuple[int, str]:
    """(exit code, output) of `git -C repo words`, stdout and stderr together; -1 when git could not run.

    Args:
        repo: the folder git runs in (-C).
        words: the words after `git -C repo`.
        timeout: the seconds the command may take.

    Returns:
        (git's exit code, stdout then stderr as text); (-1, "<error type>: <error>") when it could not run or timed out.
    """
    try:
        p = subprocess.run(["git", "-C", str(repo), *words], capture_output=True, timeout=timeout, env=env())
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, f"{type(e).__name__}: {e}"
    return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")
