"""h3.three-tools: run gives an action only the ports it names, and judges a write by the rules before it runs."""
import unittest

from harness.mcp.actions.table import ActionTable
from harness.mcp.tools.run import TOOL, UNJUDGED, Run
from harness.utils.contracts import ALLOW, ASK, REFUSE, WRITE, ActionError, Finding, McpAction, Verdict


class Look(McpAction):
    block, name, summary, needs = "t", "look", "Read a port", ("seen",)

    def run(self, ctx, args):
        return f"ports {sorted(ctx.ports)}"


class Change(McpAction):
    block, name, summary, effect = "t", "change", "Write something", WRITE
    ran = []

    def run(self, ctx, args):
        Change.ran.append(args)
        return "changed"


class Fail(McpAction):
    block, name, summary = "t", "fail", "Refuse"

    def run(self, ctx, args):
        raise ActionError("not this")


def run_with(**ports):
    table = ActionTable()
    for action in (Look, Change, Fail):
        table.add(action)
    return Run(table, ports)


def call(run, action):
    return run.call({"block": "t", "action": action, "args": {}})


class RunTest(unittest.TestCase):
    def setUp(self):
        Change.ran.clear()

    def test_an_action_gets_only_the_ports_it_needs(self):
        self.assertEqual(call(run_with(seen=1, other=2), "look").text, "ports ['seen']")
        missing = call(run_with(other=2), "look")
        self.assertTrue(missing.is_error)
        self.assertIn("seen", missing.text)

    def test_a_read_never_meets_the_judge(self):
        def judge(event):
            raise AssertionError("a read was judged")
        self.assertFalse(call(run_with(seen=1, judge=judge), "look").is_error)

    def test_a_write_runs_only_on_an_allow_a_rule_decided(self):
        events = []

        def judge_of(verdict):
            return lambda event: events.append(event) or verdict
        allowed = Verdict(ALLOW, "", (Finding("action.t.change"),))
        self.assertEqual(call(run_with(judge=judge_of(allowed)), "change").text, "changed")
        self.assertEqual((events[0].tool, events[0].input["effect"], events[0].input["action"]), (TOOL, WRITE, "change"))
        for verdict, why in ((Verdict(ALLOW), UNJUDGED), (Verdict(ASK, "no rule for it", (Finding("x"),)), "no rule"),
                             (Verdict(REFUSE, "never", (Finding("x"),)), "never")):
            with self.subTest(verdict=verdict.decision):
                result = call(run_with(judge=judge_of(verdict)), "change")
                self.assertTrue(result.is_error)
                self.assertIn(why, result.text)
        self.assertEqual(len(Change.ran), 1)

    def test_a_write_without_a_working_judge_does_not_run(self):
        def broken(event):
            raise RuntimeError("down")
        for run in (run_with(), run_with(judge=broken)):
            with self.subTest(run=run):
                self.assertTrue(call(run, "change").is_error)
        self.assertEqual(Change.ran, [])

    def test_an_action_error_is_an_error_result(self):
        result = call(run_with(), "fail")
        self.assertEqual((result.text, result.is_error), ("not this", True))


if __name__ == "__main__":
    unittest.main()
