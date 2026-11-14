"""h8.edit-gate: the files a plan allows: its patterns (** any run, * no /, ? one character, a trailing / a folder), its
add file grants and drop grants (the newest decides), and a folder above a planned file (its mkdir)."""
import unittest

from harness.gear.detect.planfiles import PlanFiles
from harness.utils.plan.files import allows, holds
from tests import tree

PLAN = {"files": ["src/**/*.py", "docs/", "a?.md", "one.py"], "tests": ["tests/test_*.py"],
        "grants": [("add", "x/y.txt"), ("drop", "one.py")]}


class FilesTest(unittest.TestCase):
    def test_patterns_grants_and_folders(self):
        cases = {"src/a.py": True, "src/deep/b/c.py": True, "src/a.js": False, "docs/x/y.md": True, "ab.md": True,
                 "abc.md": False, "tests/test_a.py": True, "tests/sub/test_a.py": False, "x/y.txt": True,
                 "one.py": False, "README.md": False}
        for rel, allowed in cases.items():
            with self.subTest(rel=rel):
                self.assertEqual(allows(PLAN, rel), allowed)

    def test_the_newest_grant_decides(self):
        self.assertTrue(allows({**PLAN, "grants": [("drop", "one.py"), ("add", "one.py")]}, "one.py"))

    def test_a_folder_above_a_planned_file_is_held(self):
        self.assertTrue(holds({"files": ["src/new/a.py"]}, "src/new"))
        self.assertFalse(holds({"files": ["src/new/a.py"]}, "lib"))

    def test_the_gate_uses_them_on_real_paths(self):
        root = str(tree(self, {})).replace("\\", "/")
        plan = {**PLAN, "root": root}
        self.assertTrue(PlanFiles.allowed(plan, f"{root}/src/k/z.py"))
        self.assertTrue(PlanFiles.allowed(plan, f"{root}/src"))  # mkdir src: held? no file named under src
        self.assertFalse(PlanFiles.allowed(plan, f"{root}/one.py"))
        self.assertFalse(PlanFiles.allowed(plan, "/elsewhere/src/a.py"))


if __name__ == "__main__":
    unittest.main()
