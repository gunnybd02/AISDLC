"""h2.one-verdict-path: the runner passes an event through the recipe's translators and detectors to decide; the recipe
and the config are read only by assemble."""
import json
import unittest

from harness.assemble.engine.ports import LedgerPort

from harness.assemble.engine.build import build_runner
from harness.assemble.engine.pipeline import PipelineBook, PipelineError
from harness.assemble.engine.runner import Runner, RunnerError
from harness.assemble.engine.select import select
from harness.gear.decide.arbiter import Decide
from harness.utils.contracts import ALLOW, ASK, REFUSE, Detector, Event, Finding, Port, Translator
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


class Breaks(Detector):
    def detect(self, event, facts):
        raise KeyError("boom")


class GivesNoDict(Translator):
    def translate(self, event):
        return ["not facts"]


class PushAction(Translator):
    VOCABULARY = ("sub", "force")

    def translate(self, event):
        return {"rule_actions": [{"sub": "push", "force": True, "detail": "one"}]}


class SeesView(Translator):
    READS = ("port_tool",)
    VOCABULARY = ("sub", "force")

    def translate(self, event, facts=None):
        return {"rule_actions": [{"sub": "push", "force": facts.get("port_tool") == "Bash", "detail": "two"}],
                "seen": dict(facts)}


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

    def test_a_gear_fault_is_a_verdict_never_a_crash(self):
        rules = Decide.load(CLAUDE_DIR)  # the real rows: gear.fault refuses, gear.fault_after allows
        before = Runner([Kind()], [Breaks()], rules).run(Event("PreToolUse", "Bash"))
        self.assertEqual(before.verdict.decision, REFUSE)  # fail closed before a tool call
        self.assertIn("Breaks: KeyError", before.verdict.reason)
        self.assertEqual([f.kind for f in before.verdict.findings], ["gear.fault"])
        for kind in ("Stop", "PostToolUse", "UserPromptSubmit"):
            after = Runner([Kind()], [Breaks()], rules).run(Event(kind, "Bash"))
            self.assertEqual(after.verdict.decision, ALLOW, kind)  # a broken gear never holds a turn
        bad = Runner([GivesNoDict()], [], rules).run(Event("PreToolUse", "Bash"))
        self.assertEqual(bad.verdict.findings[0].kind, "gear.fault")
        self.assertIn("not a dict of facts", bad.verdict.reason)
        both = Runner([Kind()], [Breaks(), SeesBash()], Decide({"tool.bash": {"verdict": REFUSE, "why": "no bash"},
                                                                 **rules.rules})).run(Event("Stop", "Bash"))
        self.assertEqual(both.verdict.decision, REFUSE)  # another detector's refusal still stands

    def test_rule_actions_of_every_giver_are_judged_by_the_when_rows(self):
        from harness.tests.gear.test_arbiter import rules, when_row
        judge = Decide.load(CLAUDE_DIR, rules(self, when_row("git.force_push", ASK, {"sub": "push", "force": True})),
                            vocabulary={"sub", "force"})
        out = Runner([PushAction(), SeesView()], [], judge, ports=[ToolPort()]).run(Event("PreToolUse", "Bash"))
        self.assertEqual(out.verdict.decision, ASK)
        self.assertEqual([(f.kind, f.detail) for f in out.verdict.findings],
                         [("git.force_push", "one"), ("git.force_push", "two")])  # both givers' actions, judged

    def test_two_translators_giving_the_same_fact_is_an_error(self):
        with self.assertRaises(RunnerError):
            Runner([Kind(), Kind()], [], Decide({})).run(Event("PreToolUse", "Bash"))

    def test_the_real_tree_builds_allows_a_plain_call_and_records_it(self):
        claude_dir = copy_tree(self)
        self.assertEqual(build_runner(claude_dir).run(Event("PreToolUse", "Read")).verdict.decision, ALLOW)
        port = LedgerPort(claude_dir)  # every call is recorded: its tool-call row and its gate span
        self.assertEqual([r["tool"] for r in port.rows("SELECT tool FROM act_tool_calls")], ["Read"])
        self.assertEqual([(r["kind"], r["status"]) for r in port.rows("SELECT kind, status FROM pl_spans")], [("gate", "ok")])


if __name__ == "__main__":
    unittest.main()
