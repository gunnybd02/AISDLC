"""h1.blocks-and-nets: each net finds its break in a fake tree and nothing in the real one."""
import unittest

from harness.nets import (bridges_net, config_net, english_net, entry_net, hints_net, imports_net, layout_net,
                          owners_net, size_net, verdict_net)
from harness.tests import CLAUDE_DIR, tree

NETS = (layout_net, imports_net, bridges_net, size_net, verdict_net, config_net, entry_net, hints_net, owners_net,
        english_net)


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

    def test_a_second_entry_folder_cannot_come_back(self):
        for rel in ("entry/boot.py", "entry/install.py"):  # the forwarders of the old paths are gone: one entry folder
            with self.subTest(rel=rel):
                self.assertIn(rel, joined(layout_net, self, {rel: ""}))
        self.assertEqual(layout_net.check(tree(self, {"harness/entry/hook.py": ""})), [])
        self.assertFalse((CLAUDE_DIR / "entry").exists())

    def test_declared_places_pass_and_double_star_crosses_folders(self):
        files = {"harness/gear/decide/arbiter.py": "", "harness/tests/gear/deep/test_x.py": "",
                 "harness/mcp/skill_docs/a/SKILL.md": ""}
        self.assertEqual(layout_net.check(tree(self, files)), [])

    def test_state_and_caches_are_not_read(self):
        files = {"state/harness.db": "", "harness/gear/__pycache__/x.pyc": "", "project/behaviors.json": ""}
        self.assertEqual(layout_net.check(tree(self, files)), [])

    def test_a_broken_layout_file_is_a_problem_not_a_crash(self):
        bad = tree(self, {"layout.json": "{"})
        self.assertIn("layout.json", " ".join(layout_net.check(tree(self, {}), bad / "layout.json")))

    def test_only_the_old_harness_record_is_skipped_under_project(self):
        self.assertIn("project/hidden.py", joined(layout_net, self, {"project/hidden.py": ""}))


class ImportsNetTest(unittest.TestCase):
    def test_a_block_importing_another_block_is_reported(self):
        for text in ("import harness.mcp.hooks", "import harness.mcp.hooks as h", "from harness import mcp",
                     "from harness.mcp import hooks", "from ..mcp import hooks", "from ..assemble.runner import R"):
            with self.subTest(text=text):
                self.assertIn("harness/gear/a.py", joined(imports_net, self, {"harness/gear/a.py": text + "\n"}))

    def test_a_block_may_import_itself_and_the_utils_library(self):
        text = "import os\nfrom harness.gear import decide\nfrom . import decide\nfrom harness.utils.contracts import ALLOW\n"
        self.assertEqual(joined(imports_net, self, {"harness/gear/a.py": text}), "")

    def test_mcp_and_assemble_are_held_too(self):
        self.assertIn("harness/mcp/a.py", joined(imports_net, self, {"harness/mcp/a.py": "import harness.gear.decide\n"}))
        self.assertIn("harness/assemble/a.py",
                      joined(imports_net, self, {"harness/assemble/a.py": "from harness.mcp import hooks\n"}))
        ok = "from harness.assemble import loader\nfrom harness.utils import contracts\n\n\ndef f():\n    import harness.nets.size_net\n"
        self.assertEqual(joined(imports_net, self, {"harness/assemble/a.py": ok}), "")

    def test_assemble_imports_the_nets_only_inside_a_function(self):
        for text in ("from harness.nets import size_net\n",
                     "try:\n    import harness.nets.size_net\nexcept ImportError:\n    pass\n"):
            with self.subTest(text=text):
                self.assertIn("harness/assemble/a.py", joined(imports_net, self, {"harness/assemble/a.py": text}))

    def test_a_file_that_does_not_decode_breaks_no_net_and_is_reported_once(self):
        root = tree(self, {})
        (root / "harness" / "gear" / "detect").mkdir(parents=True)
        (root / "harness" / "gear" / "detect" / "a.py").write_bytes(b"x = '\xe9'\n")
        found = [p for net in NETS for p in net.check(root)]
        self.assertEqual(len(found), 1)
        self.assertIn("does not decode", found[0])

    def test_a_file_that_does_not_parse_is_reported_once_and_breaks_no_net(self):
        files = {"harness/gear/a.py": "def (:\n"}
        self.assertIn("does not parse", joined(imports_net, self, files))
        for net in (bridges_net, verdict_net, config_net, entry_net):
            with self.subTest(net=net.__name__):
                self.assertEqual(net.check(tree(self, files)), [])

    def test_utils_imports_no_block(self):
        self.assertIn("harness/utils/a.py", joined(imports_net, self, {"harness/utils/a.py": "import harness.gear.decide\n"}))

    def test_entry_imports_only_assemble(self):
        self.assertIn("harness/entry/hook.py",
                      joined(imports_net, self, {"harness/entry/hook.py": "from harness.gear import decide\n"}))
        ok = "def main():\n    from harness.assemble.engine.build import run_hook\n"
        self.assertEqual(joined(imports_net, self, {"harness/entry/hook.py": ok}), "")

    def test_a_dynamic_import_outside_the_loader_is_reported(self):
        for text in ("import importlib", "from importlib import import_module", "__import__('harness.mcp')"):
            with self.subTest(text=text):
                self.assertIn("dynamic", joined(imports_net, self, {"harness/assemble/runner.py": text + "\n"}))
        self.assertEqual(joined(imports_net, self, {"harness/assemble/engine/loader.py": "import importlib\n"}), "")


class BridgesNetTest(unittest.TestCase):
    def test_a_file_that_only_re_exports_is_reported(self):
        for text in ("from harness.gear.decide.arbiter import Decide\n",
                     "from harness.gear.decide.arbiter import Decide\nD2 = Decide\n__all__ = ['D2']\n"):
            with self.subTest(text=text):
                self.assertIn("harness/gear/b.py", joined(bridges_net, self, {"harness/gear/b.py": text}))

    def test_a_file_with_code_or_only_a_docstring_passes(self):
        files = {"harness/gear/b.py": "import os\n\ndef f():\n    return os.sep\n", "harness/gear/__init__.py": '"""x"""\n'}
        self.assertEqual(bridges_net.check(tree(self, files)), [])


class SizeNetTest(unittest.TestCase):
    def test_a_long_python_or_markdown_file_is_reported(self):
        files = {"harness/gear/a.py": "x = 1\n" * 401, "docs/a.md": "x\n" * 301}
        found = joined(size_net, self, files)
        self.assertIn("harness/gear/a.py", found)
        self.assertIn("docs/a.md", found)

    def test_files_at_the_limit_pass(self):
        files = {"harness/gear/a.py": "x = 1\n" * 400, "docs/a.md": "x\n" * 300}
        self.assertEqual(size_net.check(tree(self, files)), [])


class VerdictNetTest(unittest.TestCase):
    def test_a_verdict_word_outside_decide_and_contracts_is_reported(self):
        for word in ("allow", "ask", "refuse", "deny"):
            with self.subTest(word=word):
                self.assertIn("harness/mcp/a.py", joined(verdict_net, self, {"harness/mcp/a.py": f"X = '{word}'\n"}))

    def test_a_verdict_made_outside_decide_is_reported(self):
        for text in ("from harness.utils.contracts import REFUSE\n",
                     "from harness.utils import contracts\nV = contracts.Verdict(contracts.REFUSE)\n",
                     "from harness.utils.contracts import Verdict\nV = Verdict('x')\n",
                     "from harness.utils.contracts import Verdict\ndef f(v: Verdict = Verdict('x')) -> int:\n    return 1\n",
                     "import harness.utils.contracts as c\nX = c.ASK\n"):
            with self.subTest(text=text):
                self.assertIn("harness/gear/a.py", joined(verdict_net, self, {"harness/gear/a.py": text}))

    def test_a_type_hint_may_name_verdict(self):
        text = ("from harness.utils.contracts import Verdict\nfrom harness.utils import contracts\n\n"
                "def f(v: Verdict, w: 'contracts.Verdict' = None) -> list[contracts.Verdict]:\n    x: Verdict = v\n"
                "    return [x]\n")
        self.assertEqual(verdict_net.check(tree(self, {"harness/gear/a.py": text})), [])

    def test_decide_contracts_and_longer_text_pass(self):
        files = {"harness/gear/decide/arbiter.py": "X = 'ask'\n", "harness/utils/contracts.py": "Y = 'deny'\n",
                 "harness/mcp/a.py": '"""We ask nothing."""\nX = "ask the user"\n'}
        self.assertEqual(verdict_net.check(tree(self, files)), [])



class HintsNetTest(unittest.TestCase):
    """h25.hints: every function of the harness says what it takes and gives."""

    def test_a_function_without_hints_or_docstring_is_reported(self):
        text = ('"""m"""\n\n\ndef f(a, b: int):\n    return a\n\n\nclass C:\n    def m(self, x: int) -> int:\n'
                '        return x\n\n    @staticmethod\n    def s(y) -> None:\n        """s"""\n')
        found = hints_net.check(tree(self, {"harness/gear/a.py": text}))
        self.assertEqual(found, ["hints: harness/gear/a.py:4 f has no hint for a, return",
                                 "hints: harness/gear/a.py:4 f has no docstring",
                                 "hints: harness/gear/a.py:9 m has no docstring",
                                 "hints: harness/gear/a.py:13 s has no hint for y"])

    def test_full_hints_a_docstring_and_a_bare_closure_pass(self):
        text = ('"""m"""\n\n\ndef f(a: int, *rest: str, **more: int) -> int:\n    """f"""\n'
                '    def inner(x: int) -> int:\n        return x\n    return inner(a)\n\n\n'
                'class C:\n    """c"""\n\n    def m(self, x: int) -> None:\n        """m"""\n')
        files = {"harness/gear/a.py": text, "harness/tests/gear/test_a.py": "def test_x(self):\n    pass\n"}
        self.assertEqual(hints_net.check(tree(self, files)), [])  # a test file is not read

    def test_the_harness_says_what_every_function_takes_and_gives(self):
        self.assertEqual(hints_net.check(CLAUDE_DIR), [])

class EntryNetTest(unittest.TestCase):
    def test_a_harness_import_at_the_top_of_an_entry_script_is_reported(self):
        for text in ("from harness.assemble.engine.build import run_hook\n", "import json\nimport harness.assemble.engine.build\n",
                     "try:\n    import harness.assemble.engine.build\nexcept ImportError:\n    pass\n",
                     "if True:\n    from harness.assemble import build\n"):
            with self.subTest(text=text):
                self.assertIn("imports harness", joined(entry_net, self, {"harness/entry/hook.py": MAIN + text}))

    def test_an_entry_whose_main_does_not_catch_everything_is_reported(self):
        nested = "def main():\n    def inner():\n        try:\n            pass\n        except BaseException:\n" \
                 "            return 2\n"
        for text in ("import sys\n", "def main():\n    try:\n        pass\n    except Exception:\n        return 2\n",
                     nested):
            with self.subTest(text=text):
                self.assertIn("BaseException", joined(entry_net, self, {"harness/entry/hook.py": text}))

    def test_stdlib_at_the_top_and_the_harness_inside_main_pass(self):
        text = "import sys\nfrom pathlib import Path\n\n" + MAIN
        self.assertEqual(joined(entry_net, self, {"harness/entry/hook.py": text}), "")

    def test_an_entry_inside_the_harness_is_held_to_the_same_rule(self):
        bad = MAIN + "from harness.assemble.engine.build import run_hook\n"
        self.assertIn("harness/entry/hook.py", joined(entry_net, self, {"harness/entry/hook.py": bad}))
        self.assertIn("BaseException", joined(entry_net, self, {"harness/entry/cli.py": "import sys\n"}))
        self.assertEqual(joined(entry_net, self, {"harness/gear/x.py": bad}), "")  # not an entry


MAIN = ("def main():\n    try:\n        from harness.assemble.engine.build import run_hook\n"
        "    except BaseException:\n        return 2\n\n\n")



BODY = ('    """Join the words."""\n    out = []\n    for word in words:\n        if word:\n'
        '            out.append(word.strip())\n    return " ".join(out)\n')


class OwnersNetTest(unittest.TestCase):
    def test_a_copied_function_body_is_reported_with_both_places(self):
        files = {"harness/utils/a.py": "def join(words):\n" + BODY,
                 "harness/gear/b.py": "def glue(words):\n" + BODY.replace("Join the words", "Glue them"),
                 "harness/tests/utils/test_a.py": "def join(words):\n" + BODY}  # tests are free
        self.assertEqual(owners_net.check(tree(self, files)),
                         ["owners: harness/utils/a.py:1 join is a copy of harness/gear/b.py:1 glue; import the one owner "
                          "instead"])
        self.assertEqual(owners_net.check(tree(self, {"harness/utils/a.py": "def x():\n    return 1\n",
                                                      "harness/gear/b.py": "def y():\n    return 1\n"})), [])

    def test_a_looked_up_port_in_an_action_is_reported(self):
        text = ('ACTIONS = [("plan.show", "Show")]\n\n\nclass Show:\n    def run(self, ctx, args):\n'
                '        return ctx.ports.get("units", dict)()\n')
        found = owners_net.check(tree(self, {"harness/mcp/actions/plan.py": text,
                                             "harness/mcp/tools/run.py": "def f(self):\n    return self.ports.get('x')\n"}))
        self.assertEqual(found, ["owners: harness/mcp/actions/plan.py:6 looks a port up (ports.get); declare it in needs "
                                 "and read ctx.ports[name]"])

    def test_a_next_step_that_names_no_action_is_reported(self):
        files = {"harness/mcp/actions/plan.py": 'ACTIONS = [("plan.plan_show", "Show")]\n',
                 "harness/utils/x.py": 'HINT = "then run(\'plan\', \'plan_show\') or run(\'orchestra\', \'nope\', {name})"\n'}
        self.assertEqual(owners_net.check(tree(self, files)),
                         ["owners: harness/utils/x.py:1 tells the model run('orchestra', 'nope'), which is no action"])



class EnglishNetTest(unittest.TestCase):
    def test_a_foreign_letter_is_reported_a_symbol_or_an_escape_is_not(self):
        files = {"docs/a.md": "# Notes\n\nApprove \u2192 go \u2714\n\"Duy\u1ec7t\"\n",
                 "harness/utils/a.py": 'WORD = "caf\\u00e9"  # an escape is free\nNAME = "caf\u00e9"\n',
                 "harness/tests/utils/test_a.py": 'TEXT = "Duy\u1ec7t"\n',  # the tests are free
                 "harness/utils/b.txt": "\u00fc\n"}
        self.assertEqual(english_net.check(tree(self, files)), [
            "english: docs/a.md: line 4 holds a letter outside ASCII (U+1EC7); write English, or an escape",
            "english: harness/utils/a.py: line 2 holds a letter outside ASCII (U+00E9); write English, or an escape",
            "english: harness/utils/b.txt: line 1 holds a letter outside ASCII (U+00FC); write English, or an escape"])


class ConfigNetTest(unittest.TestCase):
    def test_project_json_named_outside_the_config_door_is_reported(self):
        found = joined(config_net, self, {"harness/gear/a.py": "PATH = 'project.json'\n"})
        self.assertIn("harness/gear/a.py", found)

    def test_the_config_door_and_docstrings_pass(self):
        files = {"harness/assemble/engine/config.py": "P = 'project.json'\n",
                 "harness/gear/a.py": '"""Never reads project.json."""\n'}
        self.assertEqual(config_net.check(tree(self, files)), [])


if __name__ == "__main__":
    unittest.main()
