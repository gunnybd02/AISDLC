"""VerifyLock: one verify at a time per repository and all its worktrees: a lock on verify.lock in the git common dir,
polled every 2 s up to an hour; the system frees it when its holder dies (flock, or msvcrt on Windows)."""
from __future__ import annotations

import os
import time
from pathlib import Path

from harness.utils.git.run import GitError, git

POLL, LONGEST = 2, 3600


class LockTimeout(TimeoutError):
    """Another verify held the lock for longer than the lock waits."""


def lock_path(root: str | Path) -> Path:
    """The lock file of a repository and all its worktrees.

    Args:
        root: a folder of the repository.

    Returns:
        verify.lock in the git common dir; <root>/.verify.lock outside a repository.
    """
    try:
        common = git(root, "rev-parse", "--git-common-dir").strip()
    except GitError:
        return Path(root) / ".verify.lock"
    return (Path(root) / common).resolve() / "verify.lock"


class VerifyLock:
    """A context manager that holds the verify lock of a repository while a verify runs."""

    def __init__(self, root: str | Path, poll: float = POLL, longest: float = LONGEST) -> None:
        """Name the lock; nothing is locked before the with block.

        Args:
            root: a folder of the repository.
            poll: the seconds between two tries.
            longest: the seconds to wait before LockTimeout.
        """
        self.path, self.poll, self.longest, self.handle = lock_path(root), poll, longest, None

    def __enter__(self) -> VerifyLock:
        """Open the lock file and wait for the lock.

        Returns:
            The lock itself.

        Raises:
            LockTimeout: the lock was not free within longest seconds.
        """
        self.handle = open(self.path, "a+b")
        waited = 0
        while not self.try_lock():
            if waited >= self.longest:
                self.handle.close()
                raise LockTimeout(f"another verify holds {self.path}")
            time.sleep(self.poll)
            waited += self.poll
        return self

    def try_lock(self) -> bool:
        """Try once to take the lock without waiting.

        Returns:
            True when this process now holds it.
        """
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def __exit__(self, *exc: object) -> None:
        """Free the lock and close the file.

        Args:
            *exc: the exception type, value and traceback of the with block (not read).
        """
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
