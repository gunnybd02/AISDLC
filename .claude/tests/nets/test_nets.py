"""h1.blocks-and-nets: each net finds its break in a fake tree and nothing in the real one."""
import unittest

from nets import bridges_net, config_net, imports_net, layout_net, size_net, verdict_net
from tests import CLAUDE_DIR, tree

NETS = (layout_net, imports_net, bridges_net, size_net, verdict_net, config_net)


def joined(net, test, files):
    return " ".join(net.check(tree(test, files)))


class RealTreeTest(unittest.TestCase):
    def test_the_real_tree_is_clean(self):
        for net in NETS:
            with self.subTest(net=net.__name__):
                self.assertEqual(net.check(CLAUDE_DIR), [])


class LayoutNetTest(unittest.TestCase):
    def test_a_file_out_of_the_declared_places_is_reported(self):
        for rel in ("harness/gear/sub/x.py", "notes.txt", "harness/gear/rules/x.py"):
            with self.subTest(rel=rel):
                self.assertIn(rel, joined(layout_net, self, {rel: ""}))

    def test_declared_places_pass_and_double_star_crosses_folders(self):
        files = {"harness/gear/decide.py": "", "tests/gear/deep/test_x.py": "", "skills/a/SKILL.md": ""}
        self.assertEqual(layout_net.check(tree(self, files)), [])

    def test_state_and_caches_are_not_read(self):
        files = {"state/harness.db": "", "harness/gear/__pycache__/x.pyc": "", "project/behaviors.json": ""}
        self.assertEqual(layout_net.check(tree(self, files)), [])


class ImportsNetTest(unittest.TestCase):
    def test_a_block_importing_another_block_is_reported(self):
        for text in ("import harness.mcp.hooks", "import harness.mcp.hooks as h", "from harness import mcp",
                     "from harness.mcp import hooks", "from ..mcp import hooks", "from ..assemble.runner import R"):
            with self.subTest(text=text):
                self.assertIn("harness/gear/a.py", joined(imports_net, self, {"harness/gear/a.py": text + "\n"}))

    def test_a_block_may_import_itself_and_the_utils_library(self):
        text = "import os\nfrom harness.gear import decide\nfrom . import decide\nfrom harness.utils.contracts import ALLOW\n"
        self.assertEqual(joined(imports_net, self, {"harness/gear/a.py": text}), "")

    def test_utils_imports_no_block(self):
        self.assertIn("harness/utils/a.py", joined(imports_net, self, {"harness/utils/a.py": "import harness.gear.decide\n"}))

    def test_entry_imports_only_assemble(self):
        self.assertIn("entry/hook.py", joined(imports_net, self, {"entry/hook.py": "from harness.gear import decide\n"}))
        ok = "def main():\n    from harness.assemble.build import run_hook\n"
        self.assertEqual(joined(imports_net, self, {"entry/hook.py": ok}), "")

    def test_a_dynamic_import_outside_the_loader_is_reported(self):
        for text in ("import importlib", "from importlib import import_module", "__import__('harness.mcp')"):
            with self.subTest(text=text):
                self.assertIn("dynamic", joined(imports_net, self, {"harness/assemble/runner.py": text + "\n"}))
        self.assertEqual(joined(imports_net, self, {"harness/assemble/loader.py": "import importlib\n"}), "")


class BridgesNetTest(unittest.TestCase):
    def test_a_file_that_only_re_exports_is_reported(self):
        for text in ("from harness.gear.decide import Decide\n",
                     "from harness.gear.decide import Decide\nD2 = Decide\n__all__ = ['D2']\n"):
            with self.subTest(text=text):
                self.assertIn("harness/gear/b.py", joined(bridges_net, self, {"harness/gear/b.py": text}))

    def test_a_file_with_code_or_only_a_docstring_passes(self):
        files = {"harness/gear/b.py": "import os\n\ndef f():\n    return os.sep\n", "harness/gear/__init__.py": '"""x"""\n'}
        self.assertEqual(bridges_net.check(tree(self, files)), [])


class SizeNetTest(unittest.TestCase):
    def test_a_long_python_or_markdown_file_is_reported(self):
        files = {"harness/gear/a.py": "x = 1\n" * 501, "docs/a.md": "x\n" * 301}
        found = joined(size_net, self, files)
        self.assertIn("harness/gear/a.py", found)
        self.assertIn("docs/a.md", found)

    def test_files_at_the_limit_pass(self):
        files = {"harness/gear/a.py": "x = 1\n" * 500, "docs/a.md": "x\n" * 300}
        self.assertEqual(size_net.check(tree(self, files)), [])


class VerdictNetTest(unittest.TestCase):
    def test_a_verdict_word_outside_decide_and_contracts_is_reported(self):
        for word in ("allow", "ask", "refuse", "deny"):
            with self.subTest(word=word):
                self.assertIn("harness/mcp/a.py", joined(verdict_net, self, {"harness/mcp/a.py": f"X = '{word}'\n"}))

    def test_decide_contracts_and_longer_text_pass(self):
        files = {"harness/gear/decide.py": "X = 'ask'\n", "harness/utils/contracts.py": "Y = 'deny'\n",
                 "harness/mcp/a.py": '"""We ask nothing."""\nX = "ask the user"\n'}
        self.assertEqual(verdict_net.check(tree(self, files)), [])


class ConfigNetTest(unittest.TestCase):
    def test_project_json_named_outside_the_config_door_is_reported(self):
        found = joined(config_net, self, {"harness/gear/a.py": "PATH = 'project.json'\n"})
        self.assertIn("harness/gear/a.py", found)

    def test_the_config_door_and_docstrings_pass(self):
        files = {"harness/assemble/config.py": "P = 'project.json'\n",
                 "harness/gear/a.py": '"""Never reads project.json."""\n'}
        self.assertEqual(config_net.check(tree(self, files)), [])


if __name__ == "__main__":
    unittest.main()
