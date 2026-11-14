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


if __name__ == "__main__":
    unittest.main()
