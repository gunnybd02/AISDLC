"""VerifyLock: one verify at a time per repository and all its worktrees: a lock on verify.lock in the git common dir,
polled every 2 s up to an hour; the system frees it when its holder dies (flock, or msvcrt on Windows)."""
import os
import time
from pathlib import Path

from harness.utils.git.run import GitError, git

POLL, LONGEST = 2, 3600


class LockTimeout(TimeoutError):
    pass


def lock_path(root):
    try:
        common = git(root, "rev-parse", "--git-common-dir").strip()
    except GitError:
        return Path(root) / ".verify.lock"
    return (Path(root) / common).resolve() / "verify.lock"


class VerifyLock:
    def __init__(self, root, poll=POLL, longest=LONGEST):
        self.path, self.poll, self.longest, self.handle = lock_path(root), poll, longest, None

    def __enter__(self):
        self.handle = open(self.path, "a+b")
        waited = 0
        while not self.try_lock():
            if waited >= self.longest:
                self.handle.close()
                raise LockTimeout(f"another verify holds {self.path}")
            time.sleep(self.poll)
            waited += self.poll
        return self

    def try_lock(self):
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

    def __exit__(self, *exc):
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
