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


class ConfigTest(unittest.TestCase):
    def test_the_real_config_loads(self):
        self.assertEqual(Config.load(CLAUDE_DIR).name, "AI-harness")

    def test_the_recipe_key_is_gone_and_says_why(self):
        with self.assertRaises(ConfigError) as caught:
            Config.load(tree(self, {"project.json": json.dumps({"name": "x", "recipe": "base"})}))
        self.assertIn("select.py", str(caught.exception))

    def test_the_verify_command_is_a_list_of_words_and_may_name_this_python(self):
        good = Config.load(tree(self, {"project.json": json.dumps({"name": "x",
                                                                   "verify": ["{python}", "-m", "unittest"]})}))
        self.assertEqual(good.verify[1:], ("-m", "unittest"))
        self.assertNotEqual(good.verify[0], "{python}")
        for bad in ("python -m unittest", [], [1]):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                Config.load(tree(self, {"project.json": json.dumps({"name": "x", "verify": bad})}))

    def test_a_config_written_with_a_bom_loads(self):
        root = tree(self, {"project.json": "﻿" + json.dumps({"name": "x"})})
        self.assertEqual(Config.load(root).name, "x")

    def test_a_wrong_config_is_refused(self):
        for text in ("{", json.dumps({}), json.dumps({"name": 1}), json.dumps({"name": "x", "extra": 1}), "[]"):
            with self.subTest(text=text), self.assertRaises(ConfigError):
                Config.load(tree(self, {"project.json": text}))
        with self.assertRaises(ConfigError):
            Config.load(tree(self, {}))


if __name__ == "__main__":
    unittest.main()
