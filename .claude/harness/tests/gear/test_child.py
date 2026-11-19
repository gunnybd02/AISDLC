"""orchestra part 2: what a child session never does, judged by the hook's whole pipeline on a session that its brief
made a child (child.ask_user, child.merge, child.push_other), and nothing for a session that is no child."""
import json
import unittest

from harness.assemble.engine.build import build_runner
from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.assemble.engine.wire_mcp import items_of
from harness.gear.translate.child import pushed_branches
from harness.utils.contracts import Event, Verdict
from harness.utils.orchestra import brief
from harness.tests.e2e import copy_tree, git_repo

CARD = {"name": "api", "unit": "home", "goal": "List the orders of a user",
        "ac": ["GET /orders returns the user's orders"], "change": ["app/orders.py"], "tests": ["tests/test_orders.py"]}
SAID = "Run the git command the step needs in the repository"


class ChildGuardTest(unittest.TestCase):
    def setUp(self):
        self.claude_dir = copy_tree(self)
        self.repo = git_repo(self, {"a.py": "X = 1\n"})
        self.port = LedgerPort(self.claude_dir)
        prompt = brief.brief(7, "pd-x", CARD, "session_parent01", rounds=3)
        Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": prompt}, "c1", str(self.repo)), {},
                           Verdict("allow"))
        Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": "hello"}, "s2", str(self.repo)), {},
                           Verdict("allow"))

    def judge(self, tool, tool_input, sid="c1"):
        runner = build_runner(self.claude_dir, items_of(self.claude_dir))
        verdict = runner.run(Event("PreToolUse", tool, tool_input, sid, str(self.repo))).verdict
        return verdict.decision, [f.kind for f in verdict.findings]

    def test_a_child_never_asks_the_user(self):
        form = {"questions": [{"question": "Which one?", "header": "H", "options": [{"label": "a"}, {"label": "b"}],
                               "multiSelect": False}]}
        decision, kinds = self.judge("AskUserQuestion", form)
        self.assertEqual(decision, "refuse")
        self.assertIn("child.ask_user", kinds)
        self.assertNotIn("child.ask_user", self.judge("AskUserQuestion", form, sid="s2")[1])

    def test_a_child_never_merges(self):
        for command in ("git merge main", "git pull origin main", "git rebase main"):
            with self.subTest(command=command):
                decision, kinds = self.judge("Bash", {"command": command, "description": SAID})
                self.assertEqual(decision, "refuse")
                self.assertIn("child.merge", kinds)
        self.assertNotIn("child.merge", self.judge("Bash", {"command": "git merge main", "description": SAID},
                                                   sid="s2")[1])

    def test_a_child_pushes_only_its_own_branch(self):
        decision, kinds = self.judge("Bash", {"command": "git push origin other", "description": SAID})
        self.assertEqual(decision, "refuse")
        self.assertIn("child.push_other", kinds)
        own = self.judge("Bash", {"command": "git push origin orch/p7/api", "description": SAID})[1]
        self.assertNotIn("child.push_other", own)
        self.assertEqual(pushed_branches(["--all", "origin"], "b"), ["--all"])
        self.assertEqual(pushed_branches(["origin", "HEAD:refs/heads/b", "x:y"], "b"), ["y"])

    def test_a_child_is_never_asked_it_is_told_to_go_on(self):
        """A live child hung twice on a question nobody could answer (python3 -m unittest, git push; a push is read
        now, so a branch switch stands for the second)."""
        for command in ("cd /w && python3 -m unittest test_hello -v", "git checkout orch/p7/api"):
            with self.subTest(command=command):
                runner = build_runner(self.claude_dir, items_of(self.claude_dir))
                verdict = runner.run(Event("PreToolUse", "Bash", {"command": command, "description": SAID}, "c1",
                                           str(self.repo))).verdict
                self.assertEqual(verdict.decision, "refuse")
                self.assertTrue(verdict.reason.startswith("Nobody is at this child session's keyboard"))
                self.assertIn("Why it would have asked:", verdict.reason)
                self.assertIn("child.no_keyboard", [f.kind for f in verdict.findings])
        self.assertEqual(self.judge("Bash", {"command": "python3 -m unittest x", "description": SAID}, sid="s2")[0],
                         "ask")
        self.assertEqual(self.judge("Bash", {"command": "ls -la", "description": SAID}), ("allow", []))
        self.assertEqual(self.judge("Bash", {"command": "git push -u origin orch/p7/api", "description": SAID}),
                         ("allow", []))  # its own branch: the reader reads a push, and no rule holds it
        kept = self.port.rows("SELECT detail FROM act_rule_decisions WHERE sid = 'c1' AND rule = 'child.no_keyboard'")
        self.assertEqual({r["detail"] for r in kept}, {"Bash cd", "Bash git"})


class ChildWaitTest(unittest.TestCase):
    """Part 6: after its handback or a question a child changes nothing until a valid order; after stop it only
    exports and uploads (child.waiting, child.stopped)."""
    setUp, judge = ChildGuardTest.setUp, ChildGuardTest.judge  # the same child c1 and session s2, not its tests

    def mark(self, **keys):
        from harness.utils.plan import tickets
        self.port.write(lambda con, rec: tickets.save(con, {**tickets.latest(con, "c1"), **keys}))

    def kinds(self, tool, tool_input):
        return self.judge(tool, tool_input)[1]

    def test_a_child_that_handed_back_changes_nothing_until_an_order(self):
        from harness.utils.contracts import now
        from harness.utils.orchestra import orders
        edit = ("Write", {"file_path": str(self.repo / "app" / "orders.py"), "content": "X = 2\n"})
        push = ("mcp__harness__run", {"block": "orchestra", "action": "push", "effect": "write"})
        self.assertNotIn("child.waiting", self.kinds(*edit))
        self.mark(handback={"sha": "a" * 40, "at": now()})
        for tool, given in (edit, push, ("Bash", {"command": "git commit -am x", "description": SAID}),
                            ("mcp__harness__run", {"block": "orchestra", "action": "handback", "effect": "write"})):
            with self.subTest(tool=tool):
                decision, kinds = self.judge(tool, given)
                self.assertEqual(decision, "refuse")
                self.assertIn("child.waiting", kinds)
        for tool, given in (("Read", {"file_path": str(self.repo / "a.py")}),
                            ("mcp__harness__run", {"block": "ledger", "action": "export", "effect": "write"})):
            self.assertNotIn("child.waiting", self.kinds(tool, given))
        self.mark(**{orders.TAKEN: {"round": 1, "kind": "fix", "at": now() + 1}})  # a valid order after it
        self.assertNotIn("child.waiting", self.kinds(*edit))
        self.mark(asks=[{"n": 1, "text": "q", "at": now() + 5}])  # a question after the order: it waits again
        self.assertIn("child.waiting", self.kinds(*edit))
        self.assertNotIn("child.waiting", self.judge(*edit[:1], edit[1], sid="s2")[1])  # no child

    def test_a_stopped_child_only_exports_and_uploads(self):
        from harness.utils.contracts import now
        from harness.utils.orchestra import orders
        self.mark(**{orders.TAKEN: {"round": 2, "kind": "stop", "at": now()}})
        for tool, given in (("Write", {"file_path": str(self.repo / "a.py"), "content": "X\n"}),
                            ("Bash", {"command": "ls", "description": SAID}),
                            ("mcp__harness__run", {"block": "orchestra", "action": "take", "effect": "write"})):
            with self.subTest(tool=tool):
                self.assertIn("child.stopped", self.kinds(tool, given))
        for tool, given in (("mcp__harness__run", {"block": "ledger", "action": "export", "effect": "write"}),
                            ("mcp__Google_Drive__create_file", {"title": "x.db.gz"}),
                            ("Read", {"file_path": str(self.repo / "a.py")})):
            with self.subTest(tool=tool):
                self.assertNotIn("child.stopped", self.kinds(tool, given))


if __name__ == "__main__":
    unittest.main()
