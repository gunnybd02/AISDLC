"""h1.blocks-and-nets: the loader reads the ITEMS of hooks, mcp and gear without importing them, and refuses a wrong index."""
import unittest

from harness.assemble.engine.loader import Loader, LoaderError
from tests import CLAUDE_DIR, tree

GOOD_GEAR = '"""Block gear."""\nITEMS = [{"kind": "rule", "name": "decide", "ref": "harness.gear.decide.arbiter:Decide"}]\n'
GOOD_MCP = '"""Block mcp."""\nITEMS = []\n'
GOOD_HOOKS = '"""Block hooks."""\nITEMS = []\n'


def fake(test, gear=GOOD_GEAR, mcp=GOOD_MCP, extra=None):
    files = {"harness/gear/__init__.py": gear, "harness/gear/decide/arbiter.py": "", "harness/mcp/__init__.py": mcp,
             "harness/hooks/__init__.py": GOOD_HOOKS}
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
        for gear in ('import os\nITEMS = []\n', 'ITEMS = []\ndef f():\n    pass\n', 'ITEMS = [x for x in ()]\n',
                     'ITEMS = [{[1]: 2}]\n'):
            with self.subTest(gear=gear):
                self.assertIn("only declares", " ".join(self.problems(gear=gear)))

    def test_a_ref_outside_its_block_or_to_no_file_is_refused(self):
        for ref in ("harness.mcp.hooks:H", "harness.gear.missing:M", "nonsense"):
            with self.subTest(ref=ref):
                gear = '"""x"""\nITEMS = [{"kind": "rule", "name": "a", "ref": "%s"}]\n' % ref
                self.assertIn("ref", " ".join(self.problems(gear=gear)))

    def test_a_block_without_index_is_refused(self):
        root = tree(self, {"harness/gear/__init__.py": GOOD_GEAR, "harness/gear/decide/arbiter.py": ""})
        self.assertIn("harness/mcp/__init__.py", " ".join(Loader(root).problems()))

    def test_an_index_written_with_a_bom_reads(self):
        self.assertEqual(self.problems(gear="﻿" + GOOD_GEAR), [])

    def test_an_index_that_does_not_decode_is_a_problem(self):
        root = fake(self)
        (root / "harness" / "gear" / "__init__.py").write_bytes(b"ITEMS = ['\xe9']\n")
        self.assertIn("does not decode", " ".join(Loader(root).problems()))

    def test_items_raise_when_there_is_a_problem(self):
        with self.assertRaises(LoaderError):
            Loader(fake(self, gear="import os\n")).items()


class ActionFilesTest(unittest.TestCase):
    GOOD = 'class A:\n    pass\n\n\nclass B:\n    pass\n\n\nACTIONS = [("b.one", "A"), ("c.two", "B")]\n'

    def problems(self, text):
        return Loader(tree(self, {"harness/mcp/actions/a.py": text})).read_actions()[1]

    def test_the_real_action_files_are_read_without_a_problem(self):
        files, problems = Loader(CLAUDE_DIR).read_actions()
        self.assertEqual(problems, [])
        plan = next(f for f in files if f.module == "harness.mcp.actions.plan")
        self.assertEqual(plan.entries[:2], (("plan", "plan_present", "PlanPresent"), ("plan", "plan_revise", "PlanRevise")))

    def test_a_file_lists_block_name_and_class_and_may_hold_several_blocks(self):
        files, problems = Loader(tree(self, {"harness/mcp/actions/a.py": self.GOOD})).read_actions()
        self.assertEqual((problems, files[0].entries), ([], (("b", "one", "A"), ("c", "two", "B"))))

    def test_a_wrong_action_file_is_a_problem(self):
        for text, why in ((self.GOOD.replace('"B")]', '"Z")]'), "does not define"),
                          (self.GOOD.replace('ACTIONS = [("b.one", "A"), ("c.two", "B")]', 'ACTIONS = list([("b.one", "A")])'), "one literal"),
                          (self.GOOD.replace('"b.one"', '"one"'), "is not block.name"),
                          (self.GOOD.replace('("b.one", "A")', '"A"'), "one literal"),
                          (self.GOOD + "ACTIONS = []\n", "one literal"),
                          ("def (:\n", "does not parse")):
            with self.subTest(why=why):
                self.assertIn(why, " ".join(self.problems(text)))

    def test_an_action_declared_twice_is_a_problem(self):
        root = tree(self, {"harness/mcp/actions/a.py": self.GOOD, "harness/mcp/actions/c.py": self.GOOD})
        self.assertIn("declared already", " ".join(Loader(root).read_actions()[1]))


if __name__ == "__main__":
    unittest.main()
