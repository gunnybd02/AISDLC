"""orchestra part 3, the parent's review: check reads the receipt on the child's branch and reruns its tests itself;
accept opens one pull request (a fake GitHub here) and merges nothing; reject and answer push a note on the child's
branch for a fresh session of it, reject counts rounds; forget is recorded. A real origin, reached as https://github.com/o/r through git's insteadOf."""
import json
import subprocess
import time
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.mcp.actions.orchestra import Spawn, Started
from harness.utils.contracts import YES, ActionContext
from harness.utils.git.github import GitHubError, repo_of
from harness.utils.orchestra import locked, review
from harness.utils.plan import desk
from harness.utils.plan.approval import approvals
from harness.tests import tree
from harness.tests.e2e import copy_tree, git_repo

URL = "https://github.com/o/r"
UNITS = {"probe": {"repo": "", "path": ".", "base": "work",
                   "verify": ["{python}", "-m", "unittest", "discover", "-s", "orch-probe", "-t", "orch-probe"]}}
CARD = {"name": "hello", "unit": "probe", "goal": "Add a hello module that greets a person by name",
        "ac": ["hello('Ann') returns 'Hello, Ann'", "hello with an empty name raises ValueError"],
        "change": ["orch-probe/hello.py"], "tests": ["orch-probe/test_hello.py"]}
CODE = "def hello(name):\n    if not name:\n        raise ValueError('empty')\n    return f'Hello, {name}'\n"
TEST = ("import unittest\nfrom hello import hello\n\nclass T(unittest.TestCase):\n    def test_ac1(self):\n"
        "        self.assertEqual(hello('Ann'), 'Hello, Ann')\n\n    def test_ac2(self):\n"
        "        self.assertRaises(ValueError, hello, '')\n")


def git(repo, *args):
    """git in repo; its output."""
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


class FakeGitHub:
    """GitHub REST as orchestra calls it: a pull request is opened; a merge merges its branch into its base on the
    real origin (through the parent's clone), or answers a conflict."""

    def __init__(self, repo, conflict=False):
        self.repo, self.conflict, self.calls, self.merged = repo, conflict, [], False

    def __call__(self, method, path, fields=None):
        self.calls.append((method, path, dict(fields or {})))
        if method == "POST":
            self.head, self.base = fields["head"], fields["base"]
            return {"number": 5, "html_url": f"{URL}/pull/5"}
        if method == "GET":
            self.gets = getattr(self, "gets", 0) + 1
            if self.gets == 1 and not self.conflict:
                return {"merged": False, "mergeable": None}  # GitHub has not decided yet, right after a push
            return {"merged": self.merged, "mergeable": not self.conflict}
        if self.conflict:
            raise GitHubError("gh api PUT: Pull Request is not mergeable (HTTP 405)")
        git(self.repo, "fetch", "-q", "origin", self.head)
        git(self.repo, "merge", "-q", "--no-ff", "-m", "merge", "FETCH_HEAD")
        git(self.repo, "push", "-q", "origin", self.base)
        self.merged = True
        return {"sha": git(self.repo, "rev-parse", "HEAD").strip()}


class Scenario(unittest.TestCase):
    """A parent with an approved delegated plan of one child, its origin, and helpers that write the child's branch."""

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
        Started().run(ActionContext({"plans": self.port, "session": lambda: "s1", "limits": lambda: {"children": 3, "rounds": 3}}),
                      {"name": "hello", "sid": "session_child0001"})

    def hand_back(self, receipt=None, code=CODE, after=None):
        """Push the child's branch: its code and test, then its receipt as the tip (after: one more commit)."""
        child = tree(self, {})
        git(child, "clone", "-q", str(self.origin), ".")
        git(child, "config", "user.name", "c")
        git(child, "config", "user.email", "c@c")
        git(child, "switch", "-q", "-C", f"orch/p{self.plan}/hello", "origin/work")
        (child / "orch-probe").mkdir(exist_ok=True)
        (child / "orch-probe" / "hello.py").write_text(code, encoding="utf-8")
        (child / "orch-probe" / "test_hello.py").write_text(TEST, encoding="utf-8")
        git(child, "add", "-A")
        git(child, "commit", "-q", "-m", "work")
        body = {"name": "hello", "parent": "s1", "at": int(time.time() * 1000), "verify": "ok", "uncommitted": [],
                "refused": [], "behaviours": {f"p{self.plan}.hello.ac{n}": {
                    "what": f"AC{n}: x", "status": "active", "tests": ["orch-probe/test_hello.py"]} for n in (1, 2)}}
        (child / ".harness" / "handback").mkdir(parents=True, exist_ok=True)
        (child / ".harness" / "handback" / "hello.json").write_text(json.dumps({**body, **(receipt or {})}))
        git(child, "add", "-A")
        git(child, "commit", "-q", "-m", "receipt")
        if after:
            (child / "late.txt").write_text(after)
            git(child, "add", "-A")
            git(child, "commit", "-q", "-m", "late")
        git(child, "push", "-q", "-f", "origin", f"orch/p{self.plan}/hello")

    def check(self):
        return review.check(self.port, "s1", "hello", UNITS, [])


LOCKED_UNITS = {"probe": {**UNITS["probe"], "verify": ["{python}", "{test}"]}}  # one locked test file per run
AC_TEST = ("import unittest\nfrom hello import hello\n\nclass T(unittest.TestCase):\n    def test_ac1(self):\n"
           "        self.assertEqual(hello('Ann'), 'Hello, Ann')\n\nif __name__ == '__main__':\n    unittest.main()\n")


class LockedScenario(Scenario):
    """The same parent, with a card whose acceptance test the parent wrote and locked on the plan branch."""

    def setUp(self):
        self.port = LedgerPort(copy_tree(self))
        self.origin = tree(self, {})
        git(self.origin, "init", "-q", "--bare")
        self.repo = git_repo(self, {"README.md": "r\n"})
        git(self.repo, "remote", "add", "origin", URL)
        git(self.repo, "config", f"url.{self.origin}.insteadOf", URL)
        git(self.repo, "push", "-q", "origin", "work")
        self.port.touch_session("s1")
        card = {**CARD, "tests": [], "acTests": ["orch-probe/test_hello_ac.py"]}
        items = {**desk.normalize(desk.clean({"title": "Greet people", "what": ["w"], "files": ["notes.md"],
                                              "children": [card]})), "root": str(self.repo)}
        _, _, q = self.port.present(items, sid="s1")
        approvals(self.port, "s1", {q: YES})
        self.plan = self.port.ticket("s1")["plan"]["id"]
        (self.repo / "orch-probe").mkdir()
        (self.repo / "orch-probe" / "test_hello_ac.py").write_text(AC_TEST, encoding="utf-8")
        locked.lock(self.port, "s1", LOCKED_UNITS)
        Started().run(ActionContext({"plans": self.port, "session": lambda: "s1", "limits": lambda: {"children": 3, "rounds": 3}}),
                      {"name": "hello", "sid": "session_child0001"})

    def hand_back(self, receipt=None, code=CODE, ac=AC_TEST):
        """Push the child's branch, made from the plan branch: its code (and the acceptance test as given), then its
        receipt as the tip."""
        child = tree(self, {})
        git(child, "clone", "-q", str(self.origin), ".")
        git(child, "config", "user.name", "c")
        git(child, "config", "user.email", "c@c")
        git(child, "switch", "-q", "-C", f"orch/p{self.plan}/hello", f"origin/plan/p{self.plan}")
        (child / "orch-probe" / "hello.py").write_text(code, encoding="utf-8")
        (child / "orch-probe" / "test_hello_ac.py").write_text(ac, encoding="utf-8")
        git(child, "add", "-A")
        git(child, "commit", "-q", "-m", "work")
        body = {"name": "hello", "parent": "s1", "at": int(time.time() * 1000), "verify": "ok", "uncommitted": [],
                "refused": [], "behaviours": {}}
        (child / ".harness" / "handback").mkdir(parents=True, exist_ok=True)
        (child / ".harness" / "handback" / "hello.json").write_text(json.dumps({**body, **(receipt or {})}))
        git(child, "add", "-A")
        git(child, "commit", "-q", "-m", "receipt")
        git(child, "push", "-q", "-f", "origin", f"orch/p{self.plan}/hello")

    def check(self):
        return review.check(self.port, "s1", "hello", LOCKED_UNITS, [])


class LockedCheckTest(LockedScenario):
    def test_the_check_runs_the_locked_test_alone_and_needs_no_ac_behaviour(self):
        """s4.check.ac-only: the receipt names no AC behaviour; the locked test alone judges the code."""
        self.hand_back()
        text = self.check()
        self.assertIn("Green", text)
        self.assertIn("The locked acceptance tests are unchanged; they run alone", text)
        self.hand_back(code="def hello(name):\n    return 'Hi'\n")
        text = self.check()
        self.assertIn("Not green", text)
        self.assertIn("test_hello_ac.py", text)

    def test_a_changed_locked_test_is_red_and_named(self):
        """s4.check.locked: the child made its test easier; the check sees it before it runs anything."""
        self.hand_back(code="def hello(name):\n    return 'Hi'\n", ac=AC_TEST.replace("Hello, Ann", "Hi"))
        text = self.check()
        self.assertIn("Not green", text)
        self.assertIn("CHANGED: orch-probe/test_hello_ac.py", text)
        self.assertIn("a locked acceptance test was changed", text)


class ReviewTest(Scenario):
    def test_a_green_check_then_accept_opens_one_pull_request(self):
        self.hand_back()
        text = self.check()
        self.assertIn("Green", text)
        self.assertIn("AC 2 of 2 covered", text)
        github = FakeGitHub(self.repo)
        accepted = review.accept(self.port, "s1", "hello", UNITS, github)
        self.assertIn("pull request #5", accepted)
        self.assertIn("receipt is kept in the ledger and taken off the branch", accepted)
        self.assertNotIn("DELETE", [c[0] for c in github.calls])  # a git commit, not a file API
        on_branch = git(self.origin, "ls-tree", "-r", "--name-only", f"orch/p{self.plan}/hello")
        self.assertNotIn(".harness/handback/hello.json", on_branch)
        self.assertIn("orch-probe/hello.py", on_branch)
        self.assertIn("Keep the receipt of hello out of work",
                      git(self.origin, "log", "-1", "--format=%s", f"orch/p{self.plan}/hello"))
        self.assertEqual(self.port.ticket("s1")["crew"]["hello"]["receipt"]["name"], "hello")
        method, path, fields = github.calls[0]
        self.assertEqual((method, path, fields["head"], fields["base"]),
                         ("POST", "repos/o/r/pulls", f"orch/p{self.plan}/hello", "work"))
        self.assertIn("- AC1: hello('Ann') returns 'Hello, Ann'", fields["body"])
        entry = self.port.ticket("s1")["crew"]["hello"]
        self.assertEqual((entry["state"], entry["pr"]["number"]), ("accepted", 5))
        self.assertFalse(github.merged)

    def test_a_check_fails_on_a_red_test_a_missing_ac_or_a_receipt_that_is_not_the_tip(self):
        self.hand_back(code="def hello(name):\n    return 'Hi'\n")
        self.assertIn("RED", self.check())
        with self.assertRaisesRegex(review.ReviewError, "not passed a check"):
            review.accept(self.port, "s1", "hello", UNITS, FakeGitHub(self.repo))
        self.hand_back(receipt={"behaviours": {}})
        self.assertIn("missing: AC1", self.check())
        self.hand_back(after="x")
        with self.assertRaisesRegex(review.ReviewError, "tip of .* is not its receipt"):
            self.check()

    def ctx(self):
        return ActionContext({"plans": self.port, "session": lambda: "s1", "limits": lambda: {"children": 3, "rounds": 3}, "units": lambda: UNITS})

    def test_reject_pushes_a_send_back_note_and_a_fresh_session_reads_it(self):
        self.hand_back()
        text = review.reject(self.port, "s1", "hello", "AC2 is not tested", UNITS, 3)
        self.assertIn("round 1 of 3", text)
        self.assertNotIn("send_message", text)
        self.assertIn("run('orchestra', 'spawn', {name: 'hello'})", text)
        ref = f"orch/p{self.plan}/hello"
        note = git(self.origin, "show", f"{ref}:.harness/notes/hello/sendback-1.md")
        self.assertIn("AC2 is not tested", note)
        self.assertIn("Send-back 1 of hello", git(self.origin, "log", "-1", "--format=%s", ref))
        spawned = Spawn().run(self.ctx(), {"name": "hello"})  # the same child, in a fresh session
        prompt = json.loads(spawned[spawned.index("\n{") + 1:])["prompt"]
        self.assertIn("You are a fresh session of this child", prompt)
        self.assertIn("Read .harness/notes/hello/sendback-1.md on it first", prompt)
        self.assertNotIn("send_message", prompt)
        for n in (2, 3):
            self.assertIn(f"round {n} of 3", review.reject(self.port, "s1", "hello", "AC2 is not tested", UNITS, 3))
        with self.assertRaisesRegex(review.ReviewError, "the user decides now"):
            review.reject(self.port, "s1", "hello", "again", UNITS, 3)
        self.hand_back(receipt={"at": 1})  # a receipt older than the send-back
        with self.assertRaisesRegex(review.ReviewError, "not handed back since it was sent back"):
            self.check()

    def test_check_shows_the_question_a_child_pushed_and_stopped_on(self):
        self.hand_back()
        child = tree(self, {})
        git(child, "clone", "-q", "-b", f"orch/p{self.plan}/hello", str(self.origin), ".")
        (child / ".harness" / "notes" / "hello").mkdir(parents=True)
        (child / ".harness" / "notes" / "hello" / "question-1.md").write_text(
            "# Question 1 from hello (plan 1)\n\nShould an empty name raise ValueError or TypeError?\n")
        git(child, "add", "-A")
        git(child, "-c", "user.name=c", "-c", "user.email=c@c", "commit", "-q", "-m", "Question 1 of hello")
        git(child, "push", "-q", "origin", f"orch/p{self.plan}/hello")
        with self.assertRaisesRegex(review.ReviewError, r"asked a question and stopped: \(1\) Should an empty name "
                                                        r"raise ValueError or TypeError\? Answer it with"):
            self.check()

    def test_the_rounds_come_from_the_limits(self):
        self.hand_back()
        self.assertIn("round 1 of 1", review.reject(self.port, "s1", "hello", "AC2 is not tested", UNITS, 1))
        with self.assertRaisesRegex(review.ReviewError, "sent back 1 times: the user decides now"):
            review.reject(self.port, "s1", "hello", "again", UNITS, 1)
        spawned = Spawn().run(ActionContext({"plans": self.port, "session": lambda: "s1", "units": lambda: UNITS,
                                             "limits": lambda: {"children": 3, "rounds": 1}}), {"name": "hello"})
        self.assertIn("It may send you back at most 1 times", spawned)

    def test_a_fresh_session_keeps_the_childs_rounds(self):
        self.hand_back()
        review.reject(self.port, "s1", "hello", "AC2 is not tested", UNITS, 3)
        text = Started().run(ActionContext({"plans": self.port, "session": lambda: "s1", "limits": lambda: {"children": 3, "rounds": 3}}),
                             {"name": "hello", "sid": "session_child0002"})
        self.assertIn("runs in session session_child0002", text)
        entry = self.port.ticket("s1")["crew"]["hello"]
        self.assertEqual((entry["sid"], entry["backs"], entry["state"], entry["sessions"]),
                         ("session_child0002", 1, "running", ["session_child0001"]))
        self.assertNotIn("fresh", entry)
        with self.assertRaisesRegex(Exception, "has started already"):
            Spawn().run(self.ctx(), {"name": "hello"})

    def test_answer_pushes_a_note_and_forget_is_recorded(self):
        self.hand_back()
        text = review.answer(self.port, "s1", "hello", "use 404", UNITS)
        self.assertIn("Answer 1 to hello", text)
        self.assertNotIn("send_message", text)
        self.assertIn("use 404", git(self.origin, "show", f"orch/p{self.plan}/hello:.harness/notes/hello/answer-1.md"))
        self.assertIn("waits for a fresh session: .harness/notes/hello/answer-1.md",
                      __import__("harness.utils.orchestra.crew", fromlist=["x"]).status(self.port.ticket("s1"), 3))
        self.assertIn("forgotten", review.forget(self.port, "s1", "hello", "it will not come back"))
        entry = self.port.ticket("s1")["crew"]["hello"]
        self.assertEqual((entry["state"], entry["sent"][0]["how"]), ("forgotten", "answer"))
        self.assertEqual(repo_of("https://github.com/o/r.git"), "o/r")


if __name__ == "__main__":
    unittest.main()
