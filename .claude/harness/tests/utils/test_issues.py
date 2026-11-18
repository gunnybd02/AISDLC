"""Sessions part 3, the issues: the parent's harness opens one GitHub issue per child (a fake GitHub here), each with its
card in words and a machine block with its sha256, keeps them in the ticket, and opens none again."""
import json
import re
import unittest

from harness.mcp.actions.orchestra import Tickets
from harness.utils.contracts import ActionContext, ActionError
from harness.utils.orchestra import issues, locked
from harness.tests.utils.test_review import LOCKED_UNITS, LockedScenario


class FakeIssues:
    """GitHub REST as the issues call it: each POST opens the next issue number."""

    def __init__(self):
        self.calls = []

    def __call__(self, method, path, fields=None):
        self.calls.append((method, path, dict(fields or {})))
        n = 40 + len(self.calls)
        return {"number": n, "html_url": f"https://github.com/o/r/issues/{n}"}


class IssuesTest(LockedScenario):
    def ctx(self, github):
        return ActionContext({"plans": self.port, "session": lambda: "s1", "units": lambda: LOCKED_UNITS,
                              "github": github, "limits": lambda: {"children": 3, "rounds": 3}})

    def test_each_child_gets_one_issue_kept_in_the_ticket(self):
        """s3.issues.open: one per card, kept; a second call opens none."""
        github = FakeIssues()
        self.port.write(lambda con, rec: __import__("harness.utils.plan.tickets", fromlist=["x"]).save(
            con, {**self.port.ticket("s1"), "crew": {}}))  # no child started (the scenario started one)
        text = Tickets().run(self.ctx(github), {})
        self.assertIn("hello: issue #41 (https://github.com/o/r/issues/41) opened", text)
        (method, path, fields), = github.calls
        self.assertEqual((method, path), ("POST", "repos/o/r/issues"))
        self.assertTrue(fields["title"].startswith("hello: Add a hello module"))
        held = self.port.ticket("s1")[issues.ISSUES]["children"]["hello"]
        self.assertEqual((held["number"], held["repo"]), (41, "o/r"))
        self.assertIn("opened before", Tickets().run(self.ctx(github), {}))
        self.assertEqual(len(github.calls), 1)

    def test_the_machine_block_and_its_sha(self):
        """s3.issues.block: plan, plan sha, child, repo, branch, start, scope and AC tests; the sha of its JSON."""
        github = FakeIssues()
        self.port.write(lambda con, rec: __import__("harness.utils.plan.tickets", fromlist=["x"]).save(
            con, {**self.port.ticket("s1"), "crew": {}}))
        Tickets().run(self.ctx(github), {})
        body = github.calls[0][2]["body"]
        found = re.search(re.escape(issues.ISSUE_OPEN) + r"\n(\{.*\})\nsha256: ([0-9a-f]{64})\n" +
                          re.escape(issues.ISSUE_CLOSE), body)
        block = json.loads(found.group(1))
        ticket = self.port.ticket("s1")
        self.assertEqual(block, {"plan": ticket["draft"], "planSha": ticket["plan"]["sha"], "child": "hello",
                                 "repo": "https://github.com/o/r", "branch": f"orch/p{self.plan}/hello",
                                 "start": f"plan/p{self.plan}", "scope": ["orch-probe/hello.py"],
                                 "acTests": ["orch-probe/test_hello_ac.py"]})
        self.assertEqual(found.group(2), issues.block_sha(block))
        self.assertEqual(ticket[issues.ISSUES]["children"]["hello"]["sha"], found.group(2))
        for words in ("- AC1: hello('Ann') returns 'Hello, Ann'", "Locked acceptance tests: orch-probe/test_hello_ac.py",
                      f"Branch: orch/p{self.plan}/hello, from plan/p{self.plan}"):
            self.assertIn(words, body)

    def test_no_issue_once_a_child_has_started(self):
        with self.assertRaises(ActionError) as e:
            Tickets().run(self.ctx(FakeIssues()), {})
        self.assertIn("a child has started", str(e.exception))
        self.assertEqual(locked.plan_branch(self.plan), f"plan/p{self.plan}")


if __name__ == "__main__":
    unittest.main()
