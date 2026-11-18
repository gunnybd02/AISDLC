"""h15.ticket: the MCP server knows its session from the hook: the session whose prompt or harness tool call came last."""
import unittest

from harness.assemble.engine.ports import LedgerPort, PlanState
from harness.assemble.engine.runner import Act
from harness.utils.contracts import Event, Verdict
from harness.utils.ledger import writes
from harness.utils.shell.after import snapshot, top_of
from harness.tests import tree
from harness.tests.e2e import git_repo


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(tree(self, {}))

    def see(self, kind, tool, sid):
        Act(self.port).run(Event(kind, tool, {}, sid, "/r"), {}, Verdict("allow"))

    def test_the_last_session_to_call_the_harness_is_the_one(self):
        self.assertEqual(self.port.session(), "")
        self.see("UserPromptSubmit", "", "s1")
        self.assertEqual(self.port.session(), "s1")
        self.see("PreToolUse", "mcp__harness__run", "s2")
        self.assertEqual(self.port.session(), "s2")
        self.see("PreToolUse", "Bash", "s3")  # another tool says nothing about who calls the server
        self.see("PostToolUse", "mcp__harness__run", "s3")
        self.assertEqual(self.port.session(), "s2")
        self.see("PreToolUse", "mcp__harness__find", "s1")
        self.assertEqual(self.port.session(), "s1")


class PlanBaseTest(unittest.TestCase):
    """protect.base: the base of each repo of the plan in force counts as protected while the plan runs."""

    def test_the_base_of_the_plan_in_force_is_protected(self):
        port = LedgerPort(tree(self, {}))
        event = Event("PreToolUse", "Bash", {"command": "ls"}, "s1", "/r")
        self.assertFalse(PlanState(port).read(event)["git_view"].protected("develop"))
        port.present({"title": "Fix the parser", "files": ["a.py"], "root": "/r",
                      "repos": {"shop": {"url": "https://github.com/acme/shop", "base": "develop"},
                                "web": {"url": "https://github.com/acme/web"}}}, sid="s1")
        port.approve("s1", port.waiting()[0])
        view = PlanState(port).read(event)["git_view"]
        for branch in ("develop", "main", "master"):
            self.assertTrue(view.protected(branch), branch)
        self.assertFalse(view.protected("issue/41-order-list"))


class AfterWritesTest(unittest.TestCase):
    """s5.after.recorded: after a shell line checked after it ran, the port gives the files it changed since its
    snapshot, and nothing for a line with no snapshot or another tool."""

    def test_the_files_changed_since_the_kept_snapshot_are_given(self):
        port = LedgerPort(tree(self, {}))
        repo = git_repo(self, {"a.py": "A = 1\n"})
        top = top_of(str(repo))
        port.write(lambda con, rec: writes.keep_before(con, "s1", "t1", {top: snapshot(top)}))
        (repo / "a.py").write_text("A = 2\n", encoding="utf-8")

        def facts(call, tool="Bash", kind="PostToolUse"):
            return PlanState(port).read(Event(kind, tool, {"command": "make"}, "s1", str(repo), {}, "auto", call))
        self.assertEqual((facts("t1")["after_writes"], facts("t1")["after_unseen"]), ([f"{top}/a.py"], []))
        for given in (facts("t2"), facts("t1", tool="Write"), facts("t1", kind="PreToolUse"), facts("")):
            self.assertNotIn("after_writes", given)


if __name__ == "__main__":
    unittest.main()
