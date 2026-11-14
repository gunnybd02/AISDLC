"""h20.ship: git.commit commits named plan files (verified, guarded) and step_done adopts the commit; git.push pushes a
unit plan's branch in deliver only (never the home, never a protected branch); mr_open opens the merge request only
after the user's Yes on its full text. Push and merge request are kept in pl_git_audit."""
import json
import re
import unittest
from unittest import mock

from harness.assemble.engine.build import items_of
from harness.assemble.engine.config import Config
from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.assemble.engine.wire_mcp import ports_of
from harness.utils.contracts import YES, Event, Verdict
from harness.utils.git.run import git
from harness.utils.plan import desk, ship, tickets
from harness.utils.plan.approval import approvals
from harness.utils.plan.ship import ShipError, git_commit, git_push, mr_open
from harness.utils.plan.steps import step_done
from harness.utils.plan.verify import verify
from tests import tree
from tests.e2e import copy_tree, git_repo

TEST = "import unittest\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\n"


class ShipTest(unittest.TestCase):
    def setUp(self):
        self.claude_dir = copy_tree(self, {"project.json": json.dumps(
            {"name": "t", "verify": ["{python}", "-m", "unittest", "discover", "-s", "."], "banned": ["wip"]})})
        self.repo = git_repo(self, {"a.py": "X = 1\n", "test_a.py": TEST, "b.md": "b\n"})
        self.remote = tree(self, {})
        git(self.remote, "init", "-q", "--bare")
        git(self.repo, "remote", "add", "origin", str(self.remote))
        self.port = LedgerPort(self.claude_dir)
        ports = ports_of(items_of(self.claude_dir), self.claude_dir)
        self.commit_judge, self.git_judge = ports["commit_judge"], ports["git_judge"]
        items = {**desk.normalize(desk.clean({"title": "Set the value", "what": ["w"], "files": ["a.py", "b.md"],
                                              "tests": ["test_a.py"]})), "root": str(self.repo)}
        plan_id, _, q = self.port.present(items, sid="s1")
        approvals(self.port, "s1", {q: YES})
        self.plan_id = plan_id

    def commit(self, files, message="Set X"):
        return git_commit(self.port, "s1", files, message, self.commit_judge)

    def refused(self, why, call):
        with self.assertRaises(ShipError) as caught:
            call()
        self.assertIn(why, str(caught.exception))

    def test_git_commit_commits_named_verified_files_and_step_done_adopts_it(self):
        (self.repo / "a.py").write_text("X = 2\n", encoding="utf-8")
        self.refused("git-commit-unverified: a.py", lambda: self.commit(["a.py"]))
        verify(self.port, Config.load(self.claude_dir).verify, self.plan_id)
        for files, why in ((["."], "never ."), (["../x.py"], "outside"), (["other.py"], "git-commit-outside-plan"),
                           ([], "a list of paths")):
            with self.subTest(why=why):
                self.refused(why, lambda: self.commit(files))
        self.refused("no AI mark", lambda: self.commit(["a.py"], "Set X\n\nCo-Authored-By: Claude <x@anthropic.com>"))
        self.refused("bans", lambda: self.commit(["a.py"], "WIP set x"))
        self.assertIn("call step_done", self.commit(["a.py"]))
        self.assertEqual(self.port.ticket("s1")["noted"], [git(self.repo, "rev-parse", "HEAD").strip()])
        self.assertIn("Adopted", step_done(self.port, "s1", "Set X"))
        self.assertEqual(self.port.ticket("s1")["closeReason"], "delivered")

    def test_no_commit_without_a_plan_or_on_a_protected_branch(self):
        self.refused("git-commit-no-plan", lambda: git_commit(self.port, "s9", ["a.py"], "m", self.commit_judge))
        git(self.repo, "checkout", "-q", "-b", "main")
        self.refused("git-commit-protected-branch", lambda: self.commit(["a.py"]))

    def deliver(self):
        self.port.write(lambda con, rec: tickets.save(con, {**tickets.latest(con, "s1"), "phase": "deliver"}))

    def test_git_push_pushes_a_unit_plan_in_deliver_only(self):
        self.refused("git-push-wrong-phase", lambda: git_push(self.port, "s1", self.git_judge))
        self.deliver()
        with mock.patch.object(self.port, "is_home", return_value=True):
            self.refused("git-home-never-pushes", lambda: git_push(self.port, "s1", self.git_judge))
        self.assertIn("Pushed work", git_push(self.port, "s1", self.git_judge))
        self.assertEqual(git(self.remote, "rev-parse", "work").strip(), git(self.repo, "rev-parse", "HEAD").strip())
        (row,) = self.port.rows("SELECT kind, local_ref FROM pl_git_audit")
        self.assertEqual((row["kind"], row["local_ref"]), ("push", "work"))
        git(self.repo, "checkout", "-q", "-b", "main")
        self.refused("git-push-protected-branch", lambda: git_push(self.port, "s1", self.git_judge))

    def test_a_merge_request_opens_only_after_the_yes_on_its_full_text(self):
        self.deliver()
        self.refused("push work first", lambda: mr_open(self.port, "s1", "Set X", "Sets X to 2", "main"))
        git_push(self.port, "s1", self.git_judge)
        self.refused("AI tool's name", lambda: mr_open(self.port, "s1", "Set X", "Made with Claude Code", "main"))
        self.refused("banned word wip", lambda: mr_open(self.port, "s1", "WIP set X", "x", "main", ("wip",)))
        asked = mr_open(self.port, "s1", "Set X", "Sets X to 2", "main")
        q = re.search(r"exactly:\n(.+?)\nOptions", asked, re.S).group(1)
        self.assertTrue(q.startswith("Mở MR work → main: \"Set X\" [m"))
        event = Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": q}]}, "s1", str(self.repo))
        self.assertIn("confirms", " ".join(Act(self.port).run(event, {"answers": {q: "Cho phép"}}, Verdict("allow"))))
        self.assertIn("exactly", mr_open(self.port, "s1", "Set X", "Other text", "main"))  # another text: asked again
        with mock.patch.object(ship, "open_mr", return_value={"iid": 7, "web_url": "https://gl/x/-/merge_requests/7"}) as made, \
                mock.patch.object(ship, "project_of", return_value=("https://gl/api/v4", "group/x")):
            self.assertEqual(mr_open(self.port, "s1", "Set X", "Sets X to 2", "main"),
                             "Merge request !7 opened: https://gl/x/-/merge_requests/7")
        self.assertEqual(made.call_args.args[2:5], ("work", "main", "Set X"))
        self.assertEqual([r["kind"] for r in self.port.rows("SELECT kind FROM pl_git_audit ORDER BY at, rowid")],
                         ["push", "mr"])


if __name__ == "__main__":
    unittest.main()
