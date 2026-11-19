"""Sessions part 5, the draft pull request (utils/orchestra/draft.py): for a plan with locked tests, spawn makes the
child's branch with one start commit, opens one draft pull request into the plan branch (a fake GitHub here, a real
origin), and gives the call that watches it."""
import json
import unittest

from harness.mcp.actions.orchestra import Spawn, Tickets
from harness.utils.contracts import ActionContext
from harness.utils.orchestra import draft
from harness.utils.plan import tickets as plan_tickets
from harness.tests import tree
from harness.tests.utils.test_review import LOCKED_UNITS, LockedScenario, git


class FakeGitHub:
    """GitHub REST as tickets and spawn call it: issues are numbered from 41, a pull request is #5."""

    def __init__(self):
        self.calls = []

    def __call__(self, method, path, fields=None):
        self.calls.append((method, path, dict(fields or {})))
        if path.endswith("/pulls"):
            return {"number": 5, "html_url": "https://github.com/o/r/pull/5", "node_id": "PR_kw5"}
        n = 40 + len([c for c in self.calls if c[1].endswith("/issues")])
        return {"number": n, "html_url": f"https://github.com/o/r/issues/{n}"}

    def pulls(self):
        return [c for c in self.calls if c[1].endswith("/pulls")]


class DraftScenario(LockedScenario):
    """A locked plan whose child has its issue and has not started yet."""

    def setUp(self):
        super().setUp()
        self.port.write(lambda con, rec: plan_tickets.save(con, {**self.port.ticket("s1"), "crew": {}}))
        self.github = FakeGitHub()
        Tickets().run(self.ctx_of(), {"into": str(tree(self, {}))})

    def ctx_of(self):
        return ActionContext({"plans": self.port, "session": lambda: "s1", "units": lambda: LOCKED_UNITS,
                              "github": self.github, "limits": lambda: {"children": 3, "rounds": 3}})

    def spawn(self):
        return Spawn().run(self.ctx_of(), {"name": "hello"})


class DraftTest(DraftScenario):
    def test_spawn_opens_one_draft_after_a_start_commit_and_gives_the_watch_call(self):
        """s1.draft.open: the start commit on the child's branch, then one draft into the plan branch, kept."""
        text = self.spawn()
        ref, into = f"orch/p{self.plan}/hello", f"plan/p{self.plan}"
        self.assertEqual(git(self.origin, "log", "--format=%s", f"{into}..{ref}").splitlines(), ["#41 hello: start"])
        self.assertEqual(git(self.origin, "show", "--name-only", "--format=", ref).split(),
                         [".harness/notes/hello/start.md"])
        self.assertIn("Issue #41: https://github.com/o/r/issues/41",
                      git(self.origin, "show", f"{ref}:.harness/notes/hello/start.md"))
        (method, path, fields), = self.github.pulls()
        self.assertEqual((method, path), ("POST", "repos/o/r/pulls"))
        self.assertEqual((fields["head"], fields["base"], fields["draft"]), (ref, into, True))
        self.assertTrue(fields["title"].startswith(f"[p{self.plan}] hello: Add a hello module"))
        watch = {"owner": "o", "repo": "r", "pullNumber": 5}
        self.assertTrue(text.startswith("First watch its draft pull request #5 (https://github.com/o/r/pull/5)"))
        self.assertIn(f"mcp__claude-code-remote__subscribe_pr_activity {json.dumps(watch)}. Then ", text)
        self.assertEqual(json.loads(text[text.index("\n{") + 1:])["title"], f"Orchestra p{self.plan}: hello")
        self.assertEqual(self.port.ticket("s1")[draft.DRAFTS]["hello"],
                         {"repo": "o/r", "number": 5, "url": "https://github.com/o/r/pull/5", "node": "PR_kw5"})
        self.spawn()  # a second spawn reuses the draft: no new pull request, no new start commit
        self.assertEqual(len(self.github.pulls()), 1)
        self.assertEqual(len(git(self.origin, "log", "--format=%s", f"{into}..{ref}").splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
