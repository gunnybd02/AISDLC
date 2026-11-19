"""Sessions part 2, the lock: the parent writes the acceptance tests the cards name, lock commits them on the plan
branch plan/p<n> (made from the unit's base) and pushes it, keeping the hash of each file; a missing test stops it; a
started child stops it; spawn needs it. A real origin, reached as https://github.com/o/r through git's insteadOf."""
import subprocess
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.mcp.actions.orchestra import Lock, Spawn, Started, Tickets
from harness.utils.contracts import YES, ActionContext, ActionError
from harness.utils.ledger.writes import content_hash
from harness.utils.orchestra import locked
from harness.utils.plan import desk
from harness.utils.plan.approval import approvals
from harness.tests import tree
from harness.tests.e2e import copy_tree, git_repo

URL = "https://github.com/o/r"
UNITS = {"probe": {"repo": "", "path": ".", "base": "work", "verify": ["{python}", "-m", "unittest"]}}
CARD = {"name": "hello", "unit": "probe", "goal": "Add a hello module that greets a person by name",
        "ac": ["hello('Ann') returns 'Hello, Ann'", "hello with an empty name raises ValueError"],
        "change": ["orch-probe/hello.py"], "acTests": ["orch-probe/test_hello_ac.py"]}
AC = "import unittest\nfrom hello import hello\n\nclass T(unittest.TestCase):\n    def test_ac1(self):\n" \
     "        self.assertEqual(hello('Ann'), 'Hello, Ann')\n"


def git(repo, *args):
    """git in repo; its output."""
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


class LockTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(copy_tree(self))
        self.origin = tree(self, {})
        git(self.origin, "init", "-q", "--bare")
        self.repo = git_repo(self, {"README.md": "r\n"})
        git(self.repo, "remote", "add", "origin", URL)
        git(self.repo, "config", f"url.{self.origin}.insteadOf", URL)
        git(self.repo, "push", "-q", "origin", "work")
        self.port.touch_session("s1")
        items = {**desk.normalize(desk.clean({"title": "Greet people", "what": ["w"], "files": ["notes.md"],
                                              "children": [CARD]})), "root": str(self.repo)}
        _, _, q = self.port.present(items, sid="s1")
        approvals(self.port, "s1", {q: YES})
        self.plan = self.port.ticket("s1")["plan"]["id"]
        self.ctx = ActionContext({"plans": self.port, "session": lambda: "s1", "units": lambda: UNITS,
                                  "limits": lambda: {"children": 3, "rounds": 3},
                                  "harness_source": lambda: None})  # no workflow here: test_review locks one

    def write_test(self, text=AC):
        (self.repo / "orch-probe").mkdir(exist_ok=True)
        (self.repo / "orch-probe" / "test_hello_ac.py").write_text(text, encoding="utf-8")

    def test_lock_pushes_the_acceptance_tests_on_the_plan_branch_and_keeps_their_hashes(self):
        """s2.lock.push"""
        self.write_test()
        out = Lock().run(self.ctx, {})
        ref = f"plan/p{self.plan}"
        self.assertIn(f"Locked on {ref}: orch-probe/test_hello_ac.py", out)
        self.assertEqual(git(self.origin, "show", f"{ref}:orch-probe/test_hello_ac.py"), AC)
        self.assertEqual(git(self.origin, "rev-parse", f"{ref}~1"), git(self.origin, "rev-parse", "work"))  # from base
        held = self.port.ticket("s1")[locked.LOCK]
        self.assertEqual(held["branch"], ref)
        self.assertEqual(locked.locked_files(self.port.ticket("s1")),
                         {"orch-probe/test_hello_ac.py": content_hash(str(self.repo / "orch-probe" / "test_hello_ac.py"))})
        self.assertEqual(locked.unlocked(self.port.ticket("s1"), CARD), [])
        self.write_test(AC + "\n# more\n")
        Lock().run(self.ctx, {})  # before any child starts, a second lock moves the plan branch on
        self.assertIn("# more", git(self.origin, "show", f"{ref}:orch-probe/test_hello_ac.py"))

    def test_a_missing_acceptance_test_stops_the_lock(self):
        """s2.lock.missing"""
        with self.assertRaises(ActionError) as e:
            Lock().run(self.ctx, {})
        self.assertIn("write these acceptance tests first", str(e.exception))
        self.assertIn("orch-probe/test_hello_ac.py", str(e.exception))
        self.assertEqual(git(self.origin, "branch", "--list", f"plan/p{self.plan}"), "")

    def test_spawn_needs_the_lock_and_a_started_child_stops_a_new_one(self):
        """s2.lock.before-spawn"""
        with self.assertRaises(ActionError) as e:
            Spawn().run(self.ctx, {"name": "hello"})
        self.assertIn("run('orchestra', 'lock', {})", str(e.exception))
        self.write_test()
        Lock().run(self.ctx, {})
        with self.assertRaises(ActionError) as e:  # part 3: its issue and the ticket come first
            Spawn().run(self.ctx, {"name": "hello"})
        self.assertIn("has no issue yet", str(e.exception))
        github = lambda method, path, fields=None: {"number": 41, "html_url": f"{URL}/issues/41"}  # noqa: E731
        ctx = ActionContext({**self.ctx.ports, "github": github})
        Tickets().run(ctx, {"into": str(tree(self, {}))})
        self.assertIn("create_session", Spawn().run(ctx, {"name": "hello"}))  # it opens the draft pull request too
        from harness.utils.contracts import Event
        from harness.utils.orchestra import draft
        draft.watch_seen(self.port, Event("PostToolUse", draft.WATCH, {"owner": "o", "repo": "r", "pullNumber": 41},
                                          "s1", "/w", "Subscribed."))  # the parent watches the draft
        Started().run(self.ctx, {"name": "hello", "sid": "session_child0001"})
        with self.assertRaises(ActionError) as e:
            Lock().run(self.ctx, {})
        self.assertIn("a child has started", str(e.exception))

    def test_the_plan_branch_is_outside_the_childrens_branches(self):
        self.assertEqual(locked.plan_branch(7), "plan/p7")
        self.assertEqual(locked.in_unit({"path": "api"}, "tests/t.py"), "api/tests/t.py")
        self.assertEqual(locked.in_unit({"path": "."}, "tests/t.py"), "tests/t.py")


if __name__ == "__main__":
    unittest.main()
