"""orchestra part 3, the parent's review: check reads the child's handback comment on its draft (the receipt, whose
commit is the branch's tip) and reruns its tests itself; accept makes the draft the pull request and merges nothing;
reject and answer post comments for a fresh session of it, reject counts rounds; forget is recorded. A real origin, reached as https://github.com/o/r through git's insteadOf."""
import json
import subprocess
import time
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.mcp.actions.orchestra import Spawn, Started
from harness.utils.contracts import YES, ActionContext
from harness.utils.git.github import GitHubError, repo_of
from harness.utils.orchestra import locked, review, talk
from harness.utils.plan import desk, tickets as plan_tickets
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
    """GitHub REST as orchestra calls it: the draft's comments (the talk, oldest first) are read and posted; a pull
    request is opened; a merge merges its branch into its base on the real origin (through the parent's clone), or
    answers a conflict. A draft made ready merges the child's branch into the unit's base."""

    def __init__(self, repo, conflict=False, comments=None, base="work"):
        self.repo, self.conflict, self.calls, self.merged = repo, conflict, [], False
        self.comments, self.head, self.base = ([] if comments is None else comments), "", base
        self.runs, self.statuses, self.draft = [], [], False  # the project's CI on the head: none by default

    def head_ref(self):
        """The pull request's head: the child's branch."""
        return self.head or next(r.split("refs/heads/", 1)[1] for r in git(self.repo, "ls-remote", "--heads", "origin")
                                 .splitlines() if "refs/heads/orch/" in r)

    def __call__(self, method, path, fields=None):
        if method == "GET" and path.split("?")[0].endswith("/comments"):
            return list(self.comments)
        if method == "GET" and "/check-runs" in path:
            return {"check_runs": list(self.runs)}
        if method == "GET" and path.endswith("/status"):
            return {"state": "pending", "statuses": list(self.statuses), "total_count": len(self.statuses)}
        self.calls.append((method, path, dict(fields or {})))
        if path == "graphql" or "ready_for_review" in path:  # the draft made ready
            self.draft = False
            return {"data": {"markPullRequestReadyForReview": {"pullRequest": {"isDraft": False}}}}
        if method == "POST" and path.endswith("/comments"):  # the talk: a comment on the draft
            n = len(self.calls)
            made = {"id": 700 + n, "html_url": f"{URL}/pull/5#issuecomment-{700 + n}", "body": fields["body"]}
            self.comments.append(made)
            return made
        if method == "POST":
            self.head, self.base = fields["head"], fields["base"]
            return {"number": 5, "html_url": f"{URL}/pull/5"}
        if method == "GET":
            self.gets = getattr(self, "gets", 0) + 1
            tip = git(self.repo, "ls-remote", "origin", f"refs/heads/{self.head_ref()}").split("\t")[0]
            pr = {"head": {"sha": tip}, "base": {"ref": self.base}, "draft": self.draft}
            if self.gets == 1 and not self.conflict:
                return {**pr, "merged": False, "mergeable": None}  # GitHub has not decided yet, right after a push
            return {**pr, "merged": self.merged, "mergeable": not self.conflict}
        if self.conflict:
            raise GitHubError("gh api PUT: Pull Request is not mergeable (HTTP 405)")
        head, here = self.head_ref(), git(self.repo, "branch", "--show-current").strip()
        git(self.repo, "fetch", "-q", "origin", head, self.base)
        if here != self.base:  # merge on a detached copy of the base, then come back
            git(self.repo, "switch", "-q", "--detach", f"origin/{self.base}")
        git(self.repo, "merge", "-q", "--no-ff", "-m", "merge", f"origin/{head}")
        git(self.repo, "push", "-q", "origin", f"HEAD:refs/heads/{self.base}")
        sha = git(self.repo, "rev-parse", "HEAD").strip()
        if here != self.base:
            git(self.repo, "switch", "-q", here)
        self.merged = True
        return {"sha": sha}


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
        self.said = []  # the comments on the child's draft, oldest first, as GitHub gives them
        self.gh = FakeGitHub(self.repo, comments=self.said)

    def say(self, kind, sha, words="x", receipt=None, n=None):
        """One comment of the child on its draft, as its harness posts it (talk.body_of), for the commit sha."""
        meta = {"child": "hello", "plan": self.plan, "from": talk.CHILD, "sha": sha, **({"n": n} if n else {})}
        k = 600 + len(self.said) + 1
        self.said.append({"id": k, "html_url": f"{URL}/pull/5#issuecomment-{k}", "body": talk.body_of(
            kind, meta, [words] + ([talk.receipt_text(receipt)] if receipt is not None else []))})

    def hand_back(self, receipt=None, code=CODE, after=None):
        """Push the child's branch: its code and test, then its empty signal commit, and post its handback comment
        naming that commit (after: one more commit over it)."""
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
        git(child, "commit", "--allow-empty", "-q", "-m", "receipt")
        sha = git(child, "rev-parse", "HEAD").strip()
        if after:
            (child / "late.txt").write_text(after)
            git(child, "add", "-A")
            git(child, "commit", "-q", "-m", "late")
        git(child, "push", "-q", "-f", "origin", f"orch/p{self.plan}/hello")
        self.say("handback", sha, "Changed: hello", {**body, **(receipt or {})})

    def check(self):
        self.drafted()  # every child has a draft; its handback is a comment there
        return review.check(self.port, "s1", "hello", UNITS, [], self.gh)

    def drafted(self):
        """The child's draft as spawn keeps it (every child has one); the talk goes there. A fake GitHub for it."""
        from harness.utils.orchestra.draft import DRAFTS
        from harness.utils.plan import tickets
        self.port.write(lambda con, rec: tickets.save(con, {**tickets.latest(con, "s1"), DRAFTS: {
            "hello": {"repo": "o/r", "number": 5, "url": f"{URL}/pull/5"}}}))
        return FakeGitHub(self.repo)


LOCKED_UNITS = {"probe": {**UNITS["probe"], "verify": ["{python}", "{test}"]}}  # one locked test file per run
AC_TEST = ("import unittest\nfrom hello import hello\n\nclass T(unittest.TestCase):\n    def test_ac1(self):\n"
           "        self.assertEqual(hello('Ann'), 'Hello, Ann')\n\nif __name__ == '__main__':\n    unittest.main()\n")


class LockedScenario(Scenario):
    """The same parent, with a card whose acceptance test the parent wrote and locked (in the ledger)."""

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
        self.locked_text = locked.lock(self.port, "s1", LOCKED_UNITS)
        self.port.write(lambda con, rec: plan_tickets.save(con, {**plan_tickets.latest(con, "s1"), "drafts": {
            "hello": {"repo": "o/r", "number": 5, "url": f"{URL}/pull/5", "node": "PR_kw5", "watched": 1}}}))
        Started().run(ActionContext({"plans": self.port, "session": lambda: "s1", "limits": lambda: {"children": 3, "rounds": 3}}),
                      {"name": "hello", "sid": "session_child0001"})  # its draft is open and watched, as spawn leaves it
        self.said = []
        self.gh = FakeGitHub(self.repo, comments=self.said)  # into the base: there is no plan branch

    def hand_back(self, receipt=None, code=CODE, ac=AC_TEST):
        """Push the child's branch, made from the base: its code (and the acceptance test as given), then its empty
        signal commit, and post its handback comment naming it."""
        child = tree(self, {})
        git(child, "clone", "-q", str(self.origin), ".")
        git(child, "config", "user.name", "c")
        git(child, "config", "user.email", "c@c")
        git(child, "switch", "-q", "-C", f"orch/p{self.plan}/hello", "origin/work")
        (child / "orch-probe").mkdir(exist_ok=True)
        (child / "orch-probe" / "hello.py").write_text(code, encoding="utf-8")
        (child / "orch-probe" / "test_hello_ac.py").write_text(ac, encoding="utf-8")
        git(child, "add", "-A")
        git(child, "commit", "-q", "-m", "work")
        body = {"name": "hello", "parent": "s1", "at": int(time.time() * 1000), "verify": "ok", "uncommitted": [],
                "refused": [], "behaviours": {}}
        git(child, "commit", "--allow-empty", "-q", "-m", "receipt")
        git(child, "push", "-q", "-f", "origin", f"orch/p{self.plan}/hello")
        self.say("handback", git(child, "rev-parse", "HEAD").strip(), "Changed: hello", {**body, **(receipt or {})})

    def check(self):
        return review.check(self.port, "s1", "hello", LOCKED_UNITS, [], self.gh)


class LockedCheckTest(LockedScenario):
    def test_check_waits_for_the_project_ci_and_skips_it_when_there_is_none(self):
        """s4.check.ci-gate: red refuses naming the failed checks, running waits, none goes on; a draft that shows no
        CI is made ready once, so a CI that skips drafts may run."""
        self.hand_back()
        self.gh.runs = [{"name": "lint", "status": "completed", "conclusion": "failure", "html_url": "u/1"}]
        with self.assertRaisesRegex(review.ReviewError, "project CI is red on .*lint"):
            self.check()
        self.gh.runs = [{"name": "lint", "status": "in_progress", "conclusion": None}]
        with self.assertRaisesRegex(review.ReviewError, "has not finished"):
            self.check()
        self.gh.runs, self.gh.draft = [], True
        with self.assertRaisesRegex(review.ReviewError, "it is ready now"):
            self.check()
        self.assertFalse(self.gh.draft)
        self.assertIn("Green", self.check())  # no CI at all: the phase is skipped
        self.gh.runs = [{"name": "lint", "status": "completed", "conclusion": "success"}]
        text = self.check()
        self.assertIn("merged with the newest work", text)
        self.assertEqual(self.port.ticket("s1")["crew"]["hello"]["lastCheck"]["sha"], talk.read(self.said[-1])["sha"])

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
        self.assertIn("CHANGED on the branch (red; the parent's own copy ran): orch-probe/test_hello_ac.py", text)
        self.assertIn("'Hi' != 'Hello, Ann'", text)  # s4.check.ci-gate: the parent's own copy decides


class ReviewTest(Scenario):
    def test_a_green_check_then_accept_makes_the_draft_the_pull_request(self):
        self.hand_back()
        text = self.check()
        self.assertIn("Green", text)
        self.assertIn("AC 2 of 2 covered", text)
        github = FakeGitHub(self.repo)
        accepted = review.accept(self.port, "s1", "hello", UNITS, github)
        self.assertIn("accepted and merged: #5 into work", accepted)
        self.assertEqual([c[0] for c in github.calls], ["GET", "PUT"])  # the draft is the pull request: it merges
        on_branch = git(self.origin, "ls-tree", "-r", "--name-only", f"orch/p{self.plan}/hello")
        self.assertNotIn(".harness", on_branch)
        self.assertIn("orch-probe/hello.py", on_branch)
        self.assertEqual(self.port.ticket("s1")["crew"]["hello"]["receipt"]["name"], "hello")
        entry = self.port.ticket("s1")["crew"]["hello"]
        self.assertEqual((entry["state"], entry["pr"]["number"]), ("accepted", 5))
        self.assertTrue(github.merged)

    def test_a_check_fails_on_a_red_test_a_missing_ac_or_a_receipt_that_is_not_the_tip(self):
        self.hand_back(code="def hello(name):\n    return 'Hi'\n")
        self.assertIn("RED", self.check())
        with self.assertRaisesRegex(review.ReviewError, "not passed a check"):
            review.accept(self.port, "s1", "hello", UNITS, FakeGitHub(self.repo))
        self.hand_back(receipt={"behaviours": {}})
        self.assertIn("missing: AC1", self.check())
        self.hand_back(after="x")
        with self.assertRaisesRegex(review.ReviewError, "is not its receipt's commit"):
            self.check()

    def ctx(self):
        return ActionContext({"plans": self.port, "session": lambda: "s1", "limits": lambda: {"children": 3, "rounds": 3},
                              "units": lambda: UNITS, "github": FakeGitHub(self.repo)})  # every child gets a draft

    def test_reject_posts_a_send_back_comment_and_a_fresh_session_reads_it(self):
        self.hand_back()
        github = self.drafted()
        text = review.reject(self.port, "s1", "hello", "AC2 is not tested", 3, github)
        self.assertIn("round 1 of 3", text)
        self.assertNotIn("send_message", text)
        self.assertIn("run('orchestra', 'spawn', {name: 'hello'})", text)
        spawned = Spawn().run(self.ctx(), {"name": "hello"})  # the same child, in a fresh session
        prompt = json.loads(spawned[spawned.index("\n{") + 1:])["prompt"]
        self.assertIn("You are a fresh session of this child", prompt)
        self.assertIn("The orchestrator's last words, also a comment on your draft pull request, are why you go on: "
                      f"send-back 1 ({URL}/pull/5#issuecomment-701): Send-back 1 of 3: AC2 is not tested", prompt)
        self.assertNotIn(".harness/notes", prompt)
        self.assertNotIn("send_message", prompt)
        for n in (2, 3):
            self.assertIn(f"round {n} of 3", review.reject(self.port, "s1", "hello", "AC2 is not tested", 3, github))
        with self.assertRaisesRegex(review.ReviewError, "the user decides now"):
            review.reject(self.port, "s1", "hello", "again", 3, github)
        self.hand_back(receipt={"at": 1})  # a receipt older than the send-back
        with self.assertRaisesRegex(review.ReviewError, "not handed back since it was sent back"):
            self.check()

    def test_check_shows_the_question_a_child_pushed_and_stopped_on(self):
        self.hand_back()
        child = tree(self, {})
        git(child, "clone", "-q", "-b", f"orch/p{self.plan}/hello", str(self.origin), ".")
        git(child, "-c", "user.name=c", "-c", "user.email=c@c", "commit", "--allow-empty", "-q", "-m", "Question 1")
        git(child, "push", "-q", "origin", f"orch/p{self.plan}/hello")
        self.say("question", git(child, "rev-parse", "HEAD").strip(),
                 "Should an empty name raise ValueError or TypeError?", n=1)
        with self.assertRaisesRegex(review.ReviewError, r"asked a question and stopped: \(1\) Should an empty name "
                                                        r"raise ValueError or TypeError\? Answer it with"):
            self.check()

    def test_the_rounds_come_from_the_limits(self):
        self.hand_back()
        github = self.drafted()
        self.assertIn("round 1 of 1", review.reject(self.port, "s1", "hello", "AC2 is not tested", 1, github))
        with self.assertRaisesRegex(review.ReviewError, "sent back 1 times: the user decides now"):
            review.reject(self.port, "s1", "hello", "again", 1, github)
        spawned = Spawn().run(ActionContext({"plans": self.port, "session": lambda: "s1", "units": lambda: UNITS,
                                             "limits": lambda: {"children": 3, "rounds": 1},
                                             "github": FakeGitHub(self.repo)}), {"name": "hello"})
        self.assertIn("It may send you back at most 1 times", spawned)

    def test_a_fresh_session_keeps_the_childs_rounds(self):
        self.hand_back()
        review.reject(self.port, "s1", "hello", "AC2 is not tested", 3, self.drafted())
        text = Started().run(ActionContext({"plans": self.port, "session": lambda: "s1", "limits": lambda: {"children": 3, "rounds": 3}}),
                             {"name": "hello", "sid": "session_child0002"})
        self.assertIn("runs in session session_child0002", text)
        entry = self.port.ticket("s1")["crew"]["hello"]
        self.assertEqual((entry["sid"], entry["backs"], entry["state"], entry["sessions"]),
                         ("session_child0002", 1, "running", ["session_child0001"]))
        self.assertNotIn("fresh", entry)
        with self.assertRaisesRegex(Exception, "has started already"):
            Spawn().run(self.ctx(), {"name": "hello"})

    def test_check_reads_the_handback_comment_and_its_receipt(self):
        """s4.child.handback-comment: the receipt is the json block of the handback comment, whose commit must be the
        branch's tip; a question newer than the handback stops the check; the branch holds no file of the talk."""
        self.hand_back()
        self.assertIn("Green", self.check())
        self.assertEqual(self.port.ticket("s1")["crew"]["hello"]["handbackUrl"], f"{URL}/pull/5#issuecomment-601")
        self.assertIn('"name": "hello"', review.read(self.port, "s1", "hello", self.gh))
        ref = f"orch/p{self.plan}/hello"
        self.assertNotIn(".harness", git(self.origin, "ls-tree", "-r", "--name-only", ref))
        self.say("handback", "f" * 40, receipt=talk.block(self.said[-1]))  # its commit is not the tip
        with self.assertRaisesRegex(review.ReviewError, "is not its receipt's commit"):
            self.check()
        self.say("question", git(self.origin, "rev-parse", ref).strip(), "Which name?", n=1)
        with self.assertRaisesRegex(review.ReviewError, r"asked a question and stopped: \(1\) Which name\? Answer"):
            self.check()
        self.assertEqual(review.read(self.port, "s1", "hello", self.gh), "hello has no receipt yet.")

    def test_reject_and_answer_post_comments_and_leave_the_branch(self):
        """s3.parent.comments: each is one comment of the orchestrator on the draft; the child's branch stays where it
        was; a child without a draft is refused."""
        from harness.utils.orchestra import talk
        self.hand_back()
        with self.assertRaisesRegex(review.ReviewError, "hello has no draft pull request to post on"):
            review.reject(self.port, "s1", "hello", "AC2 is not tested", 3, FakeGitHub(self.repo))
        ref = f"orch/p{self.plan}/hello"
        tip = git(self.origin, "rev-parse", ref).strip()
        github = self.drafted()
        review.reject(self.port, "s1", "hello", "AC2 is not tested", 3, github)
        review.answer(self.port, "s1", "hello", "use 404", github)
        self.assertEqual(git(self.origin, "rev-parse", ref).strip(), tip)  # no commit on the child's branch
        posts = [(path, fields["body"]) for method, path, fields in github.calls if method == "POST"]
        self.assertEqual([p for p, _ in posts], ["repos/o/r/issues/5/comments"] * 2)
        metas = [talk.read({"body": body}) for _, body in posts]
        self.assertEqual([(m["kind"], m["from"], m["n"], m["child"]) for m in metas],
                         [("sendback", "orchestrator", 1, "hello"), ("answer", "orchestrator", 1, "hello")])
        self.assertIn("Send-back 1 of 3: AC2 is not tested", posts[0][1])
        self.assertIn("use 404", posts[1][1])

    def test_answer_posts_a_comment_and_forget_is_recorded(self):
        self.hand_back()
        text = review.answer(self.port, "s1", "hello", "use 404", self.drafted())
        self.assertIn("Answer 1 to hello", text)
        self.assertNotIn("send_message", text)
        self.assertIn(f"The answer 1 is the comment {URL}/pull/5#issuecomment-701 on its draft", text)
        self.assertIn(f"waits for a fresh session: answer 1 ({URL}/pull/5#issuecomment-701): use 404",
                      __import__("harness.utils.orchestra.crew", fromlist=["x"]).status(self.port.ticket("s1"), 3))
        self.assertIn("forgotten", review.forget(self.port, "s1", "hello", "it will not come back"))
        entry = self.port.ticket("s1")["crew"]["hello"]
        self.assertEqual((entry["state"], entry["sent"][0]["how"]), ("forgotten", "answer"))
        self.assertEqual(repo_of("https://github.com/o/r.git"), "o/r")


if __name__ == "__main__":
    unittest.main()
