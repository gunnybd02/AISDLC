"""h2.one-verdict-path: the runner passes an event through the recipe's translators and detectors to decide; the recipe
and the config are read only by assemble."""
import json
import unittest

from harness.assemble.engine.build import build_runner
from harness.assemble.engine.pipeline import PipelineBook, PipelineError
from harness.assemble.engine.runner import Runner, RunnerError
from harness.assemble.engine.select import select
from harness.gear.decide.arbiter import Decide
from harness.utils.contracts import ALLOW, ASK, Detector, Event, Finding, Port, Translator
from harness.tests import CLAUDE_DIR, tree
from harness.tests.e2e import copy_tree


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

    def test_a_pipeline_that_names_extends_is_refused(self):
        book = self.book(base={"detectors": ["d1"]}, unit={"extends": "base", "detectors": ["d2"]})
        with self.assertRaisesRegex(PipelineError, "pipeline unit: extends is not allowed: a pipeline is self-contained"):
            book.resolve("unit")

    def test_a_wrong_recipe_is_refused(self):
        cases = (("missing", {}), ("cut", {"base": {}, "cut": {"remove": ["d1"]}}), ("bad", {"bad": {"detectors": "d1"}}))
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

    def test_the_engine_puts_the_floor_under_the_pipelines_of_the_plans_units(self):
        book = self.book(base={"translators": ["t"], "detectors": ["d1", "d2"]},
                         ui={"detectors": ["ui", "d1"]}, api={"translators": ["t2"], "detectors": ["api", "ui"]}, bare={})
        mapped = {"web": "ui", "server": "api", "notes": "bare", "lost": "missing"}
        self.assertEqual(select(book, None, mapped).name, "base")
        self.assertEqual(select(book, {"services": ["docs"]}, mapped).name, "base")  # a unit with no pipeline
        self.assertEqual(select(book, {"services": ["web"]}, None).name, "base")  # no map at all
        ui = select(book, {"services": ["web"]}, mapped)
        self.assertEqual((ui.name, ui.translators, ui.detectors), ("base+ui", ("t",), ("d1", "d2", "ui")))  # floor first
        both = select(book, {"services": ["server", "web", "docs"]}, mapped)  # two units: both pipelines, each gear once
        self.assertEqual((both.name, both.translators, both.detectors),
                         ("base+api+ui", ("t", "t2"), ("d1", "d2", "api", "ui")))
        bare = select(book, {"services": ["notes"]}, mapped)  # a pipeline that lists nothing still runs the whole floor
        self.assertEqual((bare.translators, bare.detectors), (("t",), ("d1", "d2")))
        with self.assertRaises(PipelineError):
            select(book, {"services": ["lost"]}, mapped)

    def test_the_doctor_reads_every_pipeline_file(self):
        from harness.assemble.engine.checks import pipelines
        self.assertEqual(pipelines(CLAUDE_DIR), [])
        home = copy_tree(self, {"harness/assemble/pipelines/ui.json": json.dumps({"detectors": ["secret_scan", "nope"]}),
                                "harness/assemble/pipelines/old.json": json.dumps({"extends": "base"})})
        self.assertEqual(pipelines(home), [
            "pipeline old: extends is not allowed: a pipeline is self-contained; the floor runs under it by itself",
            "pipeline ui: unknown detector nope"])

    def test_a_repo_of_the_plan_runs_its_pipeline_and_one_with_no_file_is_refused(self):
        home = copy_tree(self)
        plan = {"services": ["api"], "repos": {"api": {"url": "https://github.com/acme/api", "pipeline": "backend"}}}
        with self.assertRaises(PipelineError):
            build_runner(home, plan=plan)
        (home / "harness/assemble/pipelines/backend.json").write_text(json.dumps({"detectors": ["secret_scan"]}))
        self.assertIsInstance(build_runner(home, plan=plan), Runner)


if __name__ == "__main__":
    unittest.main()
