"""h1.blocks-and-nets: the loader reads the ITEMS of mcp and gear without importing them, and refuses a wrong index."""
import unittest

from harness.assemble.loader import Loader, LoaderError
from tests import CLAUDE_DIR, tree

GOOD_GEAR = '"""Block gear."""\nITEMS = [{"kind": "rule", "name": "decide", "ref": "harness.gear.decide:Decide"}]\n'
GOOD_MCP = '"""Block mcp."""\nITEMS = []\n'


def fake(test, gear=GOOD_GEAR, mcp=GOOD_MCP, extra=None):
    files = {"harness/gear/__init__.py": gear, "harness/gear/decide.py": "", "harness/mcp/__init__.py": mcp}
    files.update(extra or {})
    return tree(test, files)


class LoaderTest(unittest.TestCase):
    def problems(self, **kw):
        return Loader(fake(self, **kw)).problems()

    def test_the_real_tree_has_no_problem(self):
        self.assertEqual(Loader(CLAUDE_DIR).problems(), [])

    def test_a_good_index_gives_its_items(self):
        items = Loader(fake(self)).items()
        self.assertEqual([(i.block, i.kind, i.name) for i in items], [("gear", "rule", "decide")])

    def test_a_kind_the_block_does_not_hold_is_refused(self):
        gear = '"""x"""\nITEMS = [{"kind": "tool", "name": "a", "ref": "harness.gear.decide:A"}]\n'
        self.assertIn("kind 'tool'", " ".join(self.problems(gear=gear)))

    def test_a_missing_field_is_refused(self):
        gear = '"""x"""\nITEMS = [{"kind": "rule", "name": "a"}]\n'
        self.assertIn("fields", " ".join(self.problems(gear=gear)))

    def test_a_name_used_twice_in_any_block_is_refused(self):
        mcp = '"""x"""\nITEMS = [{"kind": "tool", "name": "decide", "ref": "harness.mcp.decide:D"}]\n'
        found = self.problems(mcp=mcp, extra={"harness/mcp/decide.py": ""})
        self.assertIn("'decide' is declared twice", " ".join(found))

    def test_an_index_with_logic_is_refused(self):
        for gear in ('import os\nITEMS = []\n', 'ITEMS = []\ndef f():\n    pass\n', 'ITEMS = [x for x in ()]\n'):
            with self.subTest(gear=gear):
                self.assertIn("only declares", " ".join(self.problems(gear=gear)))

    def test_a_ref_outside_its_block_or_to_no_file_is_refused(self):
        for ref in ("harness.mcp.hooks:H", "harness.gear.missing:M", "nonsense"):
            with self.subTest(ref=ref):
                gear = '"""x"""\nITEMS = [{"kind": "rule", "name": "a", "ref": "%s"}]\n' % ref
                self.assertIn("ref", " ".join(self.problems(gear=gear)))

    def test_a_block_without_index_is_refused(self):
        root = tree(self, {"harness/gear/__init__.py": GOOD_GEAR, "harness/gear/decide.py": ""})
        self.assertIn("harness/mcp/__init__.py", " ".join(Loader(root).problems()))

    def test_items_raise_when_there_is_a_problem(self):
        with self.assertRaises(LoaderError):
            Loader(fake(self, gear="import os\n")).items()


if __name__ == "__main__":
    unittest.main()
