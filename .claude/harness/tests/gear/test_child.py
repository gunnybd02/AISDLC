"""orchestra part 2: what a child session never does, judged by the hook's whole pipeline on a session that its brief
made a child (child.ask_user, child.merge, child.push_other), and nothing for a session that is no child."""
import json
import unittest

from harness.assemble.engine.build import build_runner
from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.assemble.engine.wire_mcp import items_of
from harness.gear.detect.child import pushed_branches
from harness.utils.contracts import Event, Verdict
from harness.utils.orchestra import brief
from harness.tests.e2e import copy_tree, git_repo

CARD = {"name": "api", "unit": "home", "goal": "List the orders of a user",
        "ac": ["GET /orders returns the user's orders"], "change": ["app/orders.py"], "tests": ["tests/test_orders.py"]}
SAID = "Run the git command the step needs in the repository"


class ChildGuardTest(unittest.TestCase):
    def setUp(self):
        self.claude_dir = copy_tree(self, {"project.json": json.dumps({"name": "t"})})
        self.repo = git_repo(self, {"a.py": "X = 1\n"})
        self.port = LedgerPort(self.claude_dir)
        prompt = brief.brief(7, "pd-x", CARD, "session_parent01")
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


if __name__ == "__main__":
    unittest.main()
