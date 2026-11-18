"""after: the snapshot of a repository lists its changed and untracked files with their content; changed() names the
files a command made, edited or deleted, never one it restored clean or left as it was."""
import os
import subprocess
import unittest

from harness.tests import tree
from harness.tests.e2e import git_repo
from harness.utils.shell.after import changed, snapshot, top_of


class SnapshotTest(unittest.TestCase):
    """s3.after.snapshot"""

    def setUp(self):
        self.root = git_repo(self, {"a.py": "A = 1\n", "b.py": "B = 1\n", "docs/c.md": "c\n"})

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_a_clean_repository_has_no_changed_file(self):
        self.assertEqual(snapshot(str(self.root)), {})

    def test_changed_untracked_and_deleted_files_are_listed_with_their_content(self):
        self.write("a.py", "A = 2\n")
        self.write("new/d.py", "D = 1\n")
        os.remove(self.root / "b.py")
        shot = snapshot(str(self.root))
        self.assertEqual(sorted(shot), ["a.py", "b.py", "new/d.py"])
        self.assertEqual(shot["b.py"], "")  # gone
        self.assertEqual(len(shot["a.py"]), 40)

    def test_ignored_files_are_not_seen(self):
        self.write(".gitignore", "build/\n")
        subprocess.run(["git", "-C", str(self.root), "add", ".gitignore"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-q", "-m", "ignore"], check=True, capture_output=True)
        self.write("build/out.txt", "x\n")
        self.assertEqual(snapshot(str(self.root)), {})

    def test_a_folder_outside_a_repository_gives_none(self):
        folder = tree(self, {"x.txt": "x"})
        self.assertIsNone(snapshot(str(folder)))
        self.assertEqual(top_of(str(folder)), "")

    def test_the_top_of_a_repository_is_found_from_a_folder_in_it(self):
        self.assertEqual(top_of(str(self.root / "docs")), os.path.realpath(self.root).replace("\\", "/"))


class ChangedTest(unittest.TestCase):
    """s3.after.changed"""

    def setUp(self):
        self.root = git_repo(self, {"a.py": "A = 1\n", "b.py": "B = 1\n"})

    def write(self, rel, text):
        (self.root / rel).write_text(text, encoding="utf-8")

    def test_a_file_made_edited_or_deleted_by_the_command_is_changed(self):
        self.write("b.py", "B = 2\n")  # dirty before the command
        before = snapshot(str(self.root))
        self.write("a.py", "A = 2\n")
        self.write("b.py", "B = 3\n")
        self.write("n.py", "N = 1\n")
        after = snapshot(str(self.root))
        self.assertEqual(changed(before, after), ["a.py", "b.py", "n.py"])
        os.remove(self.root / "a.py")
        self.assertEqual(changed(after, snapshot(str(self.root))), ["a.py"])

    def test_a_file_restored_clean_or_left_as_it_was_is_not_changed(self):
        self.write("a.py", "A = 2\n")
        self.write("b.py", "B = 2\n")
        before = snapshot(str(self.root))
        subprocess.run(["git", "-C", str(self.root), "checkout", "--", "a.py"], check=True, capture_output=True)
        self.assertEqual(changed(before, snapshot(str(self.root))), [])


if __name__ == "__main__":
    unittest.main()
