"""Protected branches from the forge (utils/forge/protection.py): a branch the forge protects is protected, asked at
most once per 10 minutes and kept in the ledger; an unreachable forge leaves main, master and the last list protected;
a repository not on github.com is never asked."""
import subprocess
import unittest

from harness.assemble.engine.ports import GitView, LedgerPort
from harness.utils.forge.protection import TTL_MS, protected_names
from harness.utils.git.branches import DEFAULT_PROTECTED
from harness.utils.git.github import GitHubError
from harness.tests.e2e import copy_tree, git_repo


class Forge:
    """A fake forge: answers a list, or raises like an unreachable GitHub; counts the questions."""

    def __init__(self, names):
        self.names, self.asked = names, 0

    def __call__(self, slug):
        self.asked += 1
        if self.names is None:
            raise GitHubError(f"gh api GET repos/{slug}/branches: cannot reach GitHub")
        return list(self.names)


class ProtectionTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(copy_tree(self))
        self.repo = git_repo(self, {"a.py": "X = 1\n"})
        subprocess.run(["git", "-C", str(self.repo), "remote", "add", "origin", "https://github.com/acme/shop.git"],
                       check=True, capture_output=True)

    def test_a_branch_the_forge_protects_is_asked_at_most_once_per_ten_minutes(self):
        forge, t0 = Forge(["develop", "release/*"]), 1_000_000
        self.assertEqual(protected_names(self.repo, self.port, forge, t0), ["develop", "release/*"])
        self.assertEqual(protected_names(self.repo, self.port, forge, t0 + 60_000), ["develop", "release/*"])
        self.assertEqual(forge.asked, 1)  # kept in the ledger
        forge.names = ["develop"]
        self.assertEqual(protected_names(self.repo, self.port, forge, t0 + TTL_MS + 1), ["develop"])
        self.assertEqual(forge.asked, 2)
        view = GitView(self.port.path.parent.parent, DEFAULT_PROTECTED, self.port, Forge(["develop"]))
        self.assertTrue(view.protected("develop", str(self.repo)))
        self.assertFalse(view.protected("feature/x", str(self.repo)))
        self.assertFalse(view.protected("develop"))  # no repository named: no forge

    def test_an_unreachable_forge_keeps_main_master_and_the_last_list(self):
        t0 = 2_000_000
        protected_names(self.repo, self.port, Forge(["develop"]), t0)
        down = Forge(None)
        self.assertEqual(protected_names(self.repo, self.port, down, t0 + TTL_MS + 1), ["develop"])
        self.assertEqual(down.asked, 1)
        view = GitView(self.port.path.parent.parent, DEFAULT_PROTECTED, self.port, down)
        for branch in ("main", "master", "develop"):
            self.assertTrue(view.protected(branch, str(self.repo)), branch)
        never = git_repo(self, {"b.py": "Y = 1\n"})
        subprocess.run(["git", "-C", str(never), "remote", "add", "origin", "https://github.com/acme/other.git"],
                       check=True, capture_output=True)
        self.assertEqual(protected_names(never, self.port, Forge(None)), [])  # nothing ever learned
        self.assertTrue(GitView(self.port.path.parent.parent, DEFAULT_PROTECTED, self.port, Forge(None))
                        .protected("main", str(never)))

    def test_a_repository_not_on_github_is_never_asked(self):
        local = git_repo(self, {"c.py": "Z = 1\n"})
        forge = Forge(["develop"])
        self.assertEqual(protected_names(local, self.port, forge), [])
        subprocess.run(["git", "-C", str(local), "remote", "add", "origin", "https://gitlab.com/acme/shop.git"],
                       check=True, capture_output=True)
        self.assertEqual(protected_names(local, self.port, forge), [])
        self.assertEqual(forge.asked, 0)


if __name__ == "__main__":
    unittest.main()
