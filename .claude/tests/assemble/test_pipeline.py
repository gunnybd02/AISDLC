"""h2.one-verdict-path: the runner passes an event through the recipe's translators and detectors to decide; the recipe
and the config are read only by assemble."""
import json
import unittest

from harness.assemble.engine.build import build_runner
from harness.assemble.engine.config import Config, ConfigError
from harness.assemble.engine.pipeline import PipelineBook, PipelineError
from harness.assemble.engine.runner import Runner, RunnerError
from harness.assemble.engine.select import select
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


class RecipeTest(unittest.TestCase):
    def book(self, **recipes):
        return PipelineBook(tree(self, {f"{n}.json": json.dumps(r) for n, r in recipes.items()}))

    def test_an_overlay_only_adds_to_its_base(self):
        book = self.book(base={"translators": ["t1"], "detectors": ["d1"]},
                         unit={"extends": "base", "detectors": ["d2", "d1"]})
        r = book.resolve("unit")
        self.assertEqual((r.translators, r.detectors), (("t1",), ("d1", "d2")))

    def test_a_wrong_recipe_is_refused(self):
        cases = (("missing", {}), ("cut", {"base": {}, "cut": {"extends": "base", "remove": ["d1"]}}),
                 ("a", {"a": {"extends": "b"}, "b": {"extends": "a"}}), ("bad", {"bad": {"detectors": "d1"}}))
        for name, recipes in cases:
            with self.subTest(name=name), self.assertRaises(PipelineError):
                self.book(**recipes).resolve(name)

    def test_a_recipe_name_cannot_leave_the_recipes_folder(self):
        root = tree(self, {"base.json": "{}", "a/b.json": "{}", "recipes/x.json": "{}"})
        book = PipelineBook(root / "recipes")
        for name in ("../base", "../a/b", ""):
            with self.subTest(name=name), self.assertRaises(PipelineError):
                book.resolve(name)
        self.assertEqual(book.resolve("x").name, "x")

    def test_the_real_base_recipe_resolves(self):
        PipelineBook(CLAUDE_DIR / "harness" / "assemble" / "pipelines").resolve("base")

    def test_select_gives_the_floor_without_a_plan_and_never_less(self):
        book = self.book(base={"translators": ["t"], "detectors": ["d"]},
                         ui={"extends": "base", "detectors": ["ui"]}, loose={"detectors": ["ui"]})
        self.assertEqual(select(book, None).name, "base")
        self.assertEqual(select(book, {"plan_id": "p"}).name, "base")
        self.assertEqual(select(book, {"pipeline": "ui"}).detectors, ("d", "ui"))
        with self.assertRaises(PipelineError):
            select(book, {"pipeline": "loose"})


if __name__ == "__main__":
    unittest.main()
