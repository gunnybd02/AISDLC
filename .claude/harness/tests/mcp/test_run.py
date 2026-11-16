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


class SpanTest(unittest.TestCase):
    def test_each_run_leaves_one_span_with_the_argument_names_never_their_values(self):
        from harness.assemble.engine.ports import LedgerPort
        from harness.tests import tree
        port = LedgerPort(tree(self, {}))
        port.touch_session("s1")
        run = run_with(plans=port, session=lambda: "s1", seen=1)
        self.assertEqual(run.call({"block": "t", "action": "look", "args": {"password": "hunter2", "a": 1}}).text[:5], "look(")
        self.assertFalse(call(run, "look").is_error)
        self.assertTrue(call(run, "fail").is_error)
        self.assertTrue(call(run, "nothere").is_error)
        spans = [tuple(r[k] for k in r.keys()) for r in port.rows("SELECT sid, kind, status, name, attrs FROM pl_spans ORDER BY rowid")]
        self.assertEqual(spans, [("s1", "tool", "error", "t.look", '{"args": ["a", "password"]}'),
                                 ("s1", "tool", "ok", "t.look", '{"args": []}'),
                                 ("s1", "tool", "error", "t.fail", '{"args": []}'),
                                 ("s1", "tool", "error", "t.nothere", '{"args": []}')])
        self.assertNotIn("hunter2", str(port.rows("SELECT attrs FROM pl_spans")))

    def test_a_span_that_cannot_be_kept_never_changes_the_answer(self):
        class Broken:
            def span(self, *args):
                raise AssertionError("the tool must not reach a port that is no ledger port")
        self.assertEqual(call(run_with(seen=1), "look").text, "ports ['seen']")  # a server with no ledger: no span
        from harness.assemble.engine.record_port import RecordPort
        from harness.tests import tree
        port = RecordPort(tree(self, {}) / "nowhere")
        port.write = lambda change: (_ for _ in ()).throw(OSError("no ledger"))
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(call(run_with(plans=port, seen=1), "look").text, "ports ['seen']")
        self.assertIn("not recorded in the ledger (t.look): OSError: no ledger", err.getvalue())


if __name__ == "__main__":
    unittest.main()
