"""h19.commit-guards: a secret in a line a commit adds is refused; the lines it removes and other files are not read."""
import unittest

from harness.gear.decide.arbiter import Decide
from harness.gear.detect.secret import SecretScan
from harness.gear.translate.commit import CommitFacts
from harness.utils.contracts import Event
from harness.utils.git.run import git
from tests import CLAUDE_DIR
from tests.e2e import git_repo

KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


def found(repo, files):
    event = Event("PreToolUse", "HarnessCommit", {"repo": str(repo), "files": files, "message": "m"})
    return [(f.kind, f.detail) for f in SecretScan().detect(event, CommitFacts().translate(event))]


class SecretTest(unittest.TestCase):
    def test_a_secret_in_an_added_line_is_refused(self):
        repo = git_repo(self, {"a.py": f"KEY = '{KEY}'\nX = 1\n", "b.py": "Y = 1\n"})
        self.assertEqual(found(repo, ["a.py"]), [])  # already committed: not added by this commit
        (repo / "b.py").write_text(f"Y = 1\nTOKEN = 'ghp_{'a' * 36}'\n", encoding="utf-8")
        (repo / "new.cfg").write_text("url = https://bob:hunter22@example.com/x\n", encoding="utf-8")
        self.assertEqual(found(repo, ["b.py", "new.cfg"]),
                         [("commit.secret", "b.py holds a GitHub token"), ("commit.secret", "new.cfg holds a password in a URL")])
        (repo / "a.py").write_text("X = 1\n", encoding="utf-8")
        self.assertEqual(found(repo, ["a.py"]), [])  # a removed secret is no added line
        self.assertEqual(Decide.load(CLAUDE_DIR).rules["commit.secret"]["verdict"], "refuse")

    def test_each_kind(self):
        repo = git_repo(self, {"a.py": ""})
        for line in ("-----BEGIN OPENSSH PRIVATE KEY-----", f"k = '{KEY}'", "glpat-" + "x" * 20, "xoxb-" + "1" * 12,
                     "sk-ant-" + "a" * 40, "AIza" + "b" * 35):
            with self.subTest(line=line[:12]):
                (repo / "a.py").write_text(line + "\n", encoding="utf-8")
                self.assertEqual(len(found(repo, ["a.py"])), 1)
        git(repo, "checkout", "--", "a.py")


if __name__ == "__main__":
    unittest.main()
