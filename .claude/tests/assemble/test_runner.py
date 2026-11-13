"""h2.one-verdict-path: the runner passes an event through the recipe's translators and detectors to decide; the recipe
and the config are read only by assemble."""
import json
import unittest

from harness.assemble.build import build_runner
from harness.assemble.config import Config, ConfigError
from harness.assemble.recipe import RecipeBook, RecipeError
from harness.assemble.runner import Runner, RunnerError
from harness.gear.decide.arbiter import Decide
from harness.utils.contracts import ALLOW, ASK, Detector, Event, Finding, Port, Translator
from tests import CLAUDE_DIR, tree
from tests.e2e import copy_tree


class Kind(Translator):
    def translate(self, event):
        return {"kind": event.tool.lower()}


class SeesBash(Detector):
    def detect(self, event, facts):
        return [Finding("tool.bash")] if facts.get("kind") == "bash" else []


class ToolPort(Port):
    def read(self, event):
        return {"port_tool": event.tool}


class SeesPort(Detector):
    def detect(self, event, facts):
        return [Finding("port.seen")] if facts.get("port_tool") == "Edit" else []


class Notes:
    def run(self, event, facts, verdict):
        return [f"{event.tool}:{verdict.decision}"]


class RunnerTest(unittest.TestCase):
    def test_facts_reach_the_detectors_and_findings_reach_decide(self):
        runner = Runner([Kind()], [SeesBash()], Decide({}))
        self.assertEqual(runner.run(Event("PreToolUse", "Bash")).verdict.decision, ASK)
        self.assertEqual(runner.run(Event("PreToolUse", "Read")).verdict.decision, ALLOW)

    def test_ports_give_facts_and_act_runs_after_decide(self):
        out = Runner([Kind()], [SeesPort()], Decide({}), ports=[ToolPort()], act=Notes()).run(Event("PreToolUse", "Edit"))
        self.assertEqual((out.verdict.decision, out.notes), (ASK, ("Edit:" + ASK,)))

    def test_two_translators_giving_the_same_fact_is_an_error(self):
        with self.assertRaises(RunnerError):
            Runner([Kind(), Kind()], [], Decide({})).run(Event("PreToolUse", "Bash"))

    def test_the_real_tree_builds_and_allows_a_plain_call(self):
        claude_dir = copy_tree(self)
        self.assertEqual(build_runner(claude_dir).run(Event("PreToolUse", "Read")).verdict.decision, ALLOW)
        self.assertFalse((claude_dir / "state").exists())


class RecipeTest(unittest.TestCase):
    def book(self, **recipes):
        return RecipeBook(tree(self, {f"{n}.json": json.dumps(r) for n, r in recipes.items()}))

    def test_an_overlay_only_adds_to_its_base(self):
        book = self.book(base={"translators": ["t1"], "detectors": ["d1"]},
                         unit={"extends": "base", "detectors": ["d2", "d1"]})
        r = book.resolve("unit")
        self.assertEqual((r.translators, r.detectors), (("t1",), ("d1", "d2")))

    def test_a_wrong_recipe_is_refused(self):
        cases = (("missing", {}), ("cut", {"base": {}, "cut": {"extends": "base", "remove": ["d1"]}}),
                 ("a", {"a": {"extends": "b"}, "b": {"extends": "a"}}), ("bad", {"bad": {"detectors": "d1"}}))
        for name, recipes in cases:
            with self.subTest(name=name), self.assertRaises(RecipeError):
                self.book(**recipes).resolve(name)

    def test_a_recipe_name_cannot_leave_the_recipes_folder(self):
        root = tree(self, {"base.json": "{}", "a/b.json": "{}", "recipes/x.json": "{}"})
        book = RecipeBook(root / "recipes")
        for name in ("../base", "../a/b", ""):
            with self.subTest(name=name), self.assertRaises(RecipeError):
                book.resolve(name)
        self.assertEqual(book.resolve("x").name, "x")

    def test_the_real_base_recipe_resolves(self):
        RecipeBook(CLAUDE_DIR / "harness" / "assemble" / "recipes").resolve("base")


class ConfigTest(unittest.TestCase):
    def test_the_real_config_loads(self):
        self.assertEqual(Config.load(CLAUDE_DIR).recipe, "base")

    def test_the_verify_command_is_a_list_of_words_and_may_name_this_python(self):
        good = Config.load(tree(self, {"project.json": json.dumps({"name": "x", "recipe": "base",
                                                                   "verify": ["{python}", "-m", "unittest"]})}))
        self.assertEqual(good.verify[1:], ("-m", "unittest"))
        self.assertNotEqual(good.verify[0], "{python}")
        for bad in ("python -m unittest", [], [1]):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                Config.load(tree(self, {"project.json": json.dumps({"name": "x", "recipe": "base", "verify": bad})}))

    def test_a_config_written_with_a_bom_loads(self):
        root = tree(self, {"project.json": "﻿" + json.dumps({"name": "x", "recipe": "base"})})
        self.assertEqual(Config.load(root).name, "x")

    def test_a_wrong_config_is_refused(self):
        for text in ("{", json.dumps({"name": "x"}), json.dumps({"name": "x", "recipe": "base", "extra": 1}), "[]"):
            with self.subTest(text=text), self.assertRaises(ConfigError):
                Config.load(tree(self, {"project.json": text}))
        with self.assertRaises(ConfigError):
            Config.load(tree(self, {}))


if __name__ == "__main__":
    unittest.main()
