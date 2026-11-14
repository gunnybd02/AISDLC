"""h16.cli-doors: one verify at a time per repository and its worktrees, through a lock in the git common dir."""
import unittest

from harness.utils.git.run import git
from harness.utils.plan.verify_lock import LockTimeout, VerifyLock, lock_path
from tests.e2e import git_repo
from tests import tree


class VerifyLockTest(unittest.TestCase):
    def test_the_lock_sits_in_the_common_dir_shared_by_worktrees(self):
        repo = git_repo(self, {"a.py": "x\n"})
        other = tree(self, {}) / "wt"
        git(repo, "worktree", "add", "-q", str(other), "-b", "side")
        self.assertEqual(lock_path(repo), lock_path(other))
        self.assertEqual(lock_path(repo).name, "verify.lock")

    def test_a_second_verify_waits_and_gives_up_after_its_time(self):
        repo = git_repo(self, {"a.py": "x\n"})
        with VerifyLock(repo):
            with self.assertRaises(LockTimeout):
                with VerifyLock(repo, poll=0.05, longest=0.1):
                    pass
        with VerifyLock(repo, poll=0.05, longest=0.1):
            pass  # free again


if __name__ == "__main__":
    unittest.main()
