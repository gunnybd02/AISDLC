"""h21.release: a release is the code as it stands, named by the sha of its content, copied once into state/live/<sha>;
current names the one in force and only a whole release can be."""
import unittest

from harness.utils.gateway.release import build, current, publish, release_dir, stamp
from harness.tests import tree

CODE = {"harness/a.py": "A = 1\n", "entry/boot.py": "x\n", "harness/nets/n.py": "n\n", "harness/tests/test_a.py": "t\n",
        "project.json": "{}", "docs/a.md": "d\n", "harness/__pycache__/a.pyc": "junk"}


class ReleaseTest(unittest.TestCase):
    def test_the_sha_reads_the_code_only(self):
        home = tree(self, CODE)
        sha = stamp(home)
        (home / "project.json").write_text('{"name": "x"}')
        (home / "harness" / "__pycache__" / "a.pyc").write_text("other junk")
        self.assertEqual(stamp(home), sha)
        (home / "docs" / "a.md").write_text("another word\n")
        self.assertEqual(stamp(home), sha)  # a doc is no code
        (home / "harness" / "tests" / "test_a.py").write_text("t2\n")
        after_test = stamp(home)
        self.assertNotEqual(after_test, sha)  # the nets and the tests are inside the harness: part of the release
        (home / "harness" / "a.py").write_text("A = 2\n")
        self.assertNotEqual(stamp(home), after_test)

    def test_build_copies_the_code_and_publish_puts_it_in_force(self):
        home = tree(self, CODE)
        self.assertIsNone(current(home))
        sha = build(home)
        copy = release_dir(home, sha)
        self.assertEqual((copy / "harness" / "a.py").read_text(), "A = 1\n")
        self.assertFalse((copy / "harness" / "__pycache__").exists())
        self.assertFalse((copy / "project.json").exists())
        self.assertTrue((copy / "harness" / "tests" / "test_a.py").is_file())
        self.assertEqual(sorted(p.name for p in copy.iterdir()), ["entry", "harness"])  # a release is these two
        self.assertEqual(build(home), sha)  # once per sha
        publish(home, sha)
        self.assertEqual(current(home), sha)
        publish(home, "0" * 12)
        self.assertIsNone(current(home))  # a release that is not there is none


if __name__ == "__main__":
    unittest.main()
