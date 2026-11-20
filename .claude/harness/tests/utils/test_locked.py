"""Sessions part 2, the lock: the parent writes the acceptance tests the cards name, lock keeps the text and hash of
each in the ledger and pushes nothing (no plan branch); a missing test stops it; a started child stops it; spawn needs
it. A real origin, reached as https://github.com/o/r through git's insteadOf."""
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
                                  "limits": lambda: {"children": 3, "rounds": 3}})

    def write_test(self, text=AC):
        (self.repo / "orch-probe").mkdir(exist_ok=True)
        (self.repo / "orch-probe" / "test_hello_ac.py").write_text(text, encoding="utf-8")

    def test_lock_keeps_the_tests_in_the_ledger_and_pushes_no_branch(self):
        """s6.lock.ledger: the text and hash of each test are in the ledger; nothing is pushed, no plan branch and no CI
        file; a second lock before any child starts keeps the new text."""
        self.write_test()
        out = Lock().run(self.ctx, {})
        self.assertIn("Locked: orch-probe/test_hello_ac.py, their text and hash kept in the ledger; nothing is pushed", out)
        self.assertEqual(git(self.origin, "branch", "--list").split(), ["work"])  # no plan/p<n>, no other branch
        self.assertNotIn("workflow", out)
        ticket = self.port.ticket("s1")
        self.assertNotIn("branch", ticket[locked.LOCK])
        copy = tree(self, {"t.py": AC}) / "t.py"  # the same text: the parent's own copy is gone (clear)
        self.assertEqual(locked.locked_files(ticket), {"orch-probe/test_hello_ac.py": content_hash(str(copy))})
        self.assertEqual(locked.texts(self.port, ticket), {"orch-probe/test_hello_ac.py": AC})
        self.assertEqual(locked.unlocked(ticket, CARD), [])
        self.write_test(AC + "\n# more\n")
        Lock().run(self.ctx, {})  # before any child starts, a second lock keeps the new text
        self.assertIn("# more", locked.texts(self.port, self.port.ticket("s1"))["orch-probe/test_hello_ac.py"])

    def test_lock_deletes_the_untracked_copy_of_a_locked_test(self):
        """s2.lock.local-copies-gone: the ledger holds the test; the parent's tree no longer does."""
        self.write_test()
        out = Lock().run(self.ctx, {})
        self.assertFalse((self.repo / "orch-probe" / "test_hello_ac.py").exists())
        self.assertIn("Your tree keeps no copy of orch-probe/test_hello_ac.py: the ledger holds it", out)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")

    def test_lock_keeps_a_tracked_test_and_names_it(self):
        """s2.lock.tracked-kept: a test the repository tracks stays in the tree, unchanged."""
        self.write_test()
        git(self.repo, "add", "orch-probe/test_hello_ac.py")
        git(self.repo, "commit", "-q", "-m", "the test, tracked")
        out = Lock().run(self.ctx, {})
        self.assertEqual((self.repo / "orch-probe" / "test_hello_ac.py").read_text(encoding="utf-8"), AC)
        self.assertIn("Kept in your tree, as the repository tracks it: orch-probe/test_hello_ac.py.", out)
        self.assertNotIn("keeps no copy", out)
        self.assertEqual(locked.clear(self.repo, ["orch-probe/none.py"]), (["orch-probe/none.py"], []))  # gone already

    def test_a_missing_acceptance_test_stops_the_lock(self):
        """s2.lock.missing"""
        with self.assertRaises(ActionError) as e:
            Lock().run(self.ctx, {})
        self.assertIn("write these acceptance tests first", str(e.exception))
        self.assertIn("orch-probe/test_hello_ac.py", str(e.exception))
        self.assertEqual(git(self.origin, "branch", "--list").split(), ["work"])

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

    def test_a_card_path_in_its_unit(self):
        self.assertEqual(locked.in_unit({"path": "api"}, "tests/t.py"), "api/tests/t.py")
        self.assertEqual(locked.in_unit({"path": "."}, "tests/t.py"), "tests/t.py")


if __name__ == "__main__":
    unittest.main()
