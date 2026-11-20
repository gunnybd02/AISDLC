"""orchestra part 2: a child takes its card (the card plan opens by the parent's grant, no form, on its branch), pushes
its own branch, asks, and hands back: each a comment on its draft (a fake GitHub) with an empty signal commit pushed;
the receipt, written by harness code, is the json block of the handback comment. A real repository with a bare
origin."""
import json
import subprocess
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.utils.contracts import Event, Verdict
from harness.utils.git.github import GitHubError
from harness.utils.orchestra import brief, talk, work
from harness.tests import tree
from harness.tests.e2e import copy_tree, git_repo

CARD = {"name": "api", "unit": "home", "goal": "List the orders of a user",
        "ac": ["GET /orders returns the user's orders"], "change": ["app/orders.py"], "tests": ["tests/test_orders.py"]}
REPORT = {"changed": ["app/orders.py lists orders"], "checked": ["tests/test_orders.py passes"], "notChecked": [],
          "risks": ["paging is not done"], "testsChanged": [{"test": "tests/test_orders.py", "why": "new"}]}
ALLOW = Verdict("allow")
PR = {"repo": "o/r", "number": 5, "url": "https://github.com/o/r/pull/5"}  # the child's draft, as spawn opened it


class Talk:
    """GitHub REST for the comments of the draft #5 of o/r: each post is kept; refuse makes GitHub refuse it."""

    def __init__(self, refuse=False):
        self.posts, self.refuse = [], refuse

    def __call__(self, method, path, fields=None):
        if self.refuse:
            raise GitHubError("gh api POST: Bad Gateway (HTTP 502)")
        assert (method, path) == ("POST", "repos/o/r/issues/5/comments"), (method, path)
        n = 901 + len(self.posts)
        self.posts.append({"id": n, "html_url": f"https://github.com/o/r/pull/5#issuecomment-{n}", "body": fields["body"]})
        return self.posts[-1]


def git(repo, *args):
    """The output of git in repo."""
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


class WorkTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(copy_tree(self))
        self.repo = git_repo(self, {"a.py": "X = 1\n"})
        self.origin = tree(self, {})
        git(self.origin, "init", "-q", "--bare")
        git(self.repo, "remote", "add", "origin", str(self.origin))
        Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": brief.brief(7, "pd-x", CARD, "session_p1", rounds=3,
                                                                              pr=PR)}, "c1", str(self.repo)), {}, ALLOW)

    def take(self):
        return work.take(self.port, "c1", str(self.repo))

    def test_take_opens_the_card_plan_by_the_grant_on_the_child_branch(self):
        text = self.take()
        self.assertIn("approved by the grant of plan 7", text)
        self.assertEqual(git(self.repo, "branch", "--show-current").strip(), "orch/p7/api")
        plan = self.port.approved("c1")
        self.assertEqual((plan["files"], plan["branch"]), (["app/orders.py"], "orch/p7/api"))
        self.assertEqual(self.port.rows("SELECT reason FROM rec_plans")[0]["reason"], "grant")
        whats = [json.loads(r["body"])["what"] for r in self.port.rows("SELECT body FROM pl_logs")]
        self.assertIn("grant", whats)
        self.assertNotIn("form", whats)
        self.assertIn("p7.api.ac1", self.port.registry(plan))
        self.assertIn("is open already", self.take())
        with self.assertRaisesRegex(work.WorkError, "no child"):
            work.take(self.port, "s9", str(self.repo))

    def test_take_and_push_refuse_a_drifted_locked_test(self):
        """s7.child.drift: a locked acceptance test changed or gone stops take and push and is named; put back as the
        start commit made it, both go on."""
        from harness.utils.ledger.writes import content_hash
        rel = "tests/test_api_ac.py"
        (self.repo / "tests").mkdir()
        (self.repo / rel).write_text("# locked\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "#7 api: start")
        git(self.repo, "push", "-q", "origin", "work")
        locks = {rel: content_hash(str(self.repo / rel))}
        prompt = brief.brief(7, "pd-x", {**CARD, "acTests": [rel]}, "session_p1", rounds=3, start="work", pr=PR,
                             locks=locks)
        self.assertIn(json.dumps(locks), prompt)
        Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": prompt}, "c3", str(self.repo)), {}, ALLOW)
        (self.repo / rel).write_text("# changed by the child\n", encoding="utf-8")
        with self.assertRaisesRegex(work.WorkError, f"{rel}: a locked acceptance test differs"):
            work.take(self.port, "c3", str(self.repo))
        git(self.repo, "checkout", "-q", "--", rel)
        self.assertIn("approved by the grant", work.take(self.port, "c3", str(self.repo)))  # untouched: it goes on
        push = lambda: work.push(self.port, "c3", lambda repo, args: ALLOW)  # noqa: E731
        (self.repo / rel).unlink()
        with self.assertRaisesRegex(work.WorkError, "put it back|Put it back"):
            push()
        git(self.repo, "checkout", "-q", "--", rel)
        self.assertIn("Pushed orch/p7/api", push())

    def test_a_child_with_locked_tests_starts_from_the_plan_branch(self):
        """s3.child.start: the brief names the plan branch; take makes the child's branch from it, so the locked
        acceptance test is in the clone; the card plan names it as the proof of each AC but never as a file to edit."""
        git(self.repo, "push", "-q", "origin", "work")
        git(self.repo, "switch", "-q", "-c", "plan/p7")
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_web_ac.py").write_text("# locked\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "locked")
        git(self.repo, "push", "-q", "origin", "plan/p7")
        git(self.repo, "switch", "-q", "work")
        git(self.repo, "branch", "-q", "-D", "plan/p7")
        web = {**CARD, "name": "web", "change": ["app/web.py"], "tests": [], "acTests": ["tests/test_web_ac.py"]}
        text = brief.brief(7, "pd-x", web, "session_p1", rounds=3, start="plan/p7")
        self.assertIn("pull request into plan/p7", text)
        self.assertIn("Acceptance tests (locked): tests/test_web_ac.py", text)
        Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": text}, "c2", str(self.repo)), {}, ALLOW)
        self.assertEqual(self.port.ticket("c2")["child"]["start"], "plan/p7")
        self.assertIn("new from origin/plan/p7", work.take(self.port, "c2", str(self.repo)))
        self.assertEqual(git(self.repo, "branch", "--show-current").strip(), "orch/p7/web")
        self.assertTrue((self.repo / "tests" / "test_web_ac.py").is_file())
        plan = self.port.approved("c2")
        self.assertNotIn("tests/test_web_ac.py", plan["files"] + plan.get("tests", []))
        self.assertEqual({b["test"] for b in plan["behaviors"]}, {"tests/test_web_ac.py"})

    def test_a_child_pushes_its_own_branch_only_as_the_rules_allow(self):
        with self.assertRaisesRegex(work.WorkError, "take your card first"):
            work.push(self.port, "c1", lambda repo, words: ALLOW)
        self.take()
        with self.assertRaisesRegex(work.WorkError, "not now"):
            work.push(self.port, "c1", lambda repo, words: Verdict("ask", "not now"))
        self.assertIn("Pushed orch/p7/api", work.push(self.port, "c1", lambda repo, words: ALLOW))
        self.assertIn("orch/p7/api", git(self.origin, "branch", "--list"))
        git(self.repo, "switch", "-q", "work")
        with self.assertRaisesRegex(work.WorkError, "pushes only orch/p7/api"):
            work.push(self.port, "c1", lambda repo, words: ALLOW)

    def test_a_question_is_a_comment_and_an_empty_commit_and_the_child_stops(self):
        """s4.child.question-comment: one empty signal commit and one question comment naming its sha, no file under
        .harness; a failed post leaves no commit and refuses."""
        github = Talk()
        with self.assertRaisesRegex(work.WorkError, "take your card first"):
            work.ask(self.port, "c1", "Which status code?", lambda *a: ALLOW, lambda *a: ALLOW, github)
        self.take()
        first = work.ask(self.port, "c1", "Which status code for a closed account?", lambda *a: ALLOW,
                         lambda *a: ALLOW, github)
        second = work.ask(self.port, "c1", "Is paging needed?", lambda *a: ALLOW, lambda *a: ALLOW, github)
        for text in (first, second):
            self.assertNotIn("send_message", text)
            self.assertIn("Then stop: end your turn", text)
        self.assertIn("Question 2 is the comment https://github.com/o/r/pull/5#issuecomment-902 on your draft", second)
        metas = [talk.read(c) for c in github.posts]
        self.assertEqual([(m["kind"], m["n"], m["from"], m["child"]) for m in metas],
                         [("question", 1, "child", "api"), ("question", 2, "child", "api")])
        self.assertIn("Which status code for a closed account?", github.posts[0]["body"])
        tip = git(self.origin, "rev-parse", "orch/p7/api").strip()
        self.assertEqual(metas[1]["sha"], tip)
        self.assertEqual(git(self.origin, "show", "--name-only", "--format=", tip).strip(), "")  # an empty commit
        self.assertNotIn(".harness", git(self.origin, "ls-tree", "-r", "--name-only", "orch/p7/api"))
        self.assertEqual([(a["n"], a["sha"]) for a in self.port.ticket("c1")["asks"]], [(1, metas[0]["sha"]), (2, tip)])
        head = git(self.repo, "rev-parse", "HEAD")
        with self.assertRaisesRegex(work.WorkError, "was not posted on your draft #5"):
            work.ask(self.port, "c1", "Why?", lambda *a: ALLOW, lambda *a: ALLOW, Talk(refuse=True))
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), head)  # its commit was taken back
        self.assertEqual(len(self.port.ticket("c1")["asks"]), 2)
        with self.assertRaisesRegex(work.WorkError, "one to 400"):
            work.ask(self.port, "c1", " ", lambda *a: ALLOW, lambda *a: ALLOW, github)
        with self.assertRaisesRegex(work.WorkError, "a secret"):
            work.ask(self.port, "c1", "Why?", lambda *a: Verdict("refuse", "a secret"), lambda *a: ALLOW, github)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), head)

    def test_the_question_and_handback_of_a_child_with_an_issue_start_with_its_prefix(self):
        """s2.commit.notes: "#N <name>: " starts the commits harness code writes for a child with an issue."""
        issue = {"repo": "o/r", "number": 41, "url": "https://github.com/o/r/issues/41", "sha": "a" * 64}
        prompt = brief.brief(7, "pd-x", CARD, "session_p1", rounds=3, issue=issue,
                             ticket_file={"title": "t.csv", "sha256": "b" * 64}, pr=PR)
        self.assertIn('Every commit names #41: it starts "#41 api: ", and the harness writes that.', prompt)
        Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": prompt}, "c3", str(self.repo)), {}, ALLOW)
        work.take(self.port, "c3", str(self.repo))
        work.ask(self.port, "c3", "Which status code?", lambda *a: ALLOW, lambda *a: ALLOW, Talk())
        work.handback(self.port, "c3", REPORT, lambda *a: ALLOW, lambda *a: ALLOW, Talk())
        self.assertEqual(git(self.origin, "log", "-2", "--format=%s", "orch/p7/api").splitlines(),
                         ["#41 api: Handback of api (plan 7)", "#41 api: Question 1 of api (plan 7)"])

    def test_take_registers_with_one_comment_and_commits_nothing(self):
        """s3.register.comment: the registration is one comment on the issue before the card plan opens; the branch
        gets no commit, and a second registration posts none."""
        from harness.utils.ledger.store import note
        from harness.utils.orchestra import register, talk
        issue = {"repo": "o/r", "number": 41, "url": "https://github.com/o/r/issues/41", "sha": "a" * 64}
        prompt = brief.brief(7, "pd-x", CARD, "session_p1", rounds=3, issue=issue,
                             ticket_file={"title": "t.csv", "sha256": "b" * 64})
        Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": prompt}, "c3", str(self.repo)), {}, ALLOW)
        kept = json.dumps({"issue": "a" * 64, "ticket": "b" * 64, "plan": "f" * 64})
        self.port.write(lambda con, rec: note(con, register.REGISTERED, "orch/p7/api", 41, kept, "c3", 1))
        posts = []

        def github(method, path, fields=None):
            self.assertTrue(path.startswith("repos/o/r/issues/41/comments"))
            if method == "GET":
                return list(posts)
            posts.append({"id": 700 + len(posts), "html_url": f"{issue['url']}#c{len(posts)}", "body": fields["body"]})
            return posts[-1]
        start = git(self.repo, "rev-parse", "HEAD").strip()
        text = work.take(self.port, "c3", str(self.repo), lambda repo: register.on_issue(self.port, "c3", github))
        self.assertIn("Card plan", text)
        self.assertEqual(git(self.repo, "log", "--format=%s", f"{start}..HEAD"), "")  # nothing committed
        self.assertEqual(self.port.approved("c3")["base"], start)
        meta = talk.read(posts[0])
        self.assertEqual({k: meta[k] for k in ("kind", "child", "from", "branch", "issueSha", "ticketSha256", "planSha",
                                               "format", "draft")},
                         {"kind": "register", "child": "api", "from": "child", "branch": "orch/p7/api",
                          "issueSha": "a" * 64, "ticketSha256": "b" * 64, "planSha": "f" * 64,
                          "format": "harness-register/1", "draft": "pd-x"})
        grant = [json.loads(r["body"]) for r in self.port.rows("SELECT body FROM pl_logs")
                 if json.loads(r["body"]).get("what") == "grant"][-1]
        self.assertTrue(grant["by"].endswith(", registration #41 in comment 700"), grant["by"])
        self.assertEqual(register.on_issue(self.port, "c3", github)["comment"], 700)  # held: none posted again
        self.assertEqual(len(posts), 1)
        self.assertIsNone(register.on_issue(self.port, "c1", github))  # no issue: nothing to register

    def test_a_fresh_session_takes_the_pushed_branch(self):
        """A fresh session tracks the child's pushed branch; the orchestrator's words are in its brief, not on it."""
        self.take()
        git(self.repo, "push", "-q", "origin", "orch/p7/api")
        fresh = tree(self, {})  # a new machine: a clone of origin and its own ledger
        git(fresh, "clone", "-q", str(self.origin), ".")
        port = LedgerPort(copy_tree(self))
        prompt = brief.brief(7, "pd-x", CARD, "session_p1", resume="send-back 1 (url): AC1 is not tested", rounds=3)
        Act(port).run(Event("UserPromptSubmit", "", {"prompt": prompt}, "c2", str(fresh)), {}, ALLOW)
        text = work.take(port, "c2", str(fresh))
        self.assertIn("you are on orch/p7/api (tracked)", text)
        self.assertNotIn("Notes on your branch", text)

    def test_the_handback_is_a_comment_with_the_receipt_and_an_empty_commit(self):
        """s4.child.handback-comment: the report and the receipt (a json block) are one handback comment naming the
        empty signal commit, pushed; the branch holds no receipt file."""
        github = Talk()
        self.take()
        with self.assertRaisesRegex(work.WorkError, "changed names at least one point"):
            work.handback(self.port, "c1", {**REPORT, "changed": []}, lambda *a: ALLOW, lambda *a: ALLOW, github)
        (self.repo / "scratch.txt").write_text("left over\n", encoding="utf-8")
        text = work.handback(self.port, "c1", REPORT, lambda *a: ALLOW, lambda *a: ALLOW, github, store_on=True)
        self.assertIn("Handback posted as the comment https://github.com/o/r/pull/5#issuecomment-901 on your draft", text)
        self.assertNotIn("send_message", text)
        self.assertTrue(text.endswith("You send no message; the orchestrator reads your draft and your branch."))
        self.assertIn("Save your ledger to the store: run('ledger', 'export', {reason: 'handback'})", text)
        post, = github.posts
        self.assertIn("Changed: app/orders.py lists orders", post["body"])
        self.assertIn("Risks: paging is not done", post["body"])
        receipt, meta = talk.block(post), talk.read(post)
        self.assertEqual((receipt["name"], receipt["plan"], receipt["parent"], receipt["verify"]),
                         ("api", 7, "session_p1", "missing"))
        self.assertEqual(receipt["report"]["risks"], ["paging is not done"])
        self.assertEqual(receipt["uncommitted"], ["scratch.txt"])
        self.assertIn("p7.api.ac1", receipt["behaviours"])
        tip = git(self.origin, "rev-parse", "orch/p7/api").strip()
        self.assertEqual((meta["kind"], meta["sha"]), ("handback", tip))
        self.assertEqual(self.port.ticket("c1")["handback"]["sha"], tip)
        self.assertNotIn(".harness", git(self.origin, "ls-tree", "-r", "--name-only", "orch/p7/api"))
        with self.assertRaisesRegex(work.WorkError, "commit is stopped"):
            work.handback(self.port, "c1", REPORT, lambda *a: Verdict("refuse", "a secret"), lambda *a: ALLOW, github)

    def test_the_card_plan_stays_open_after_its_last_step_and_the_child_stays_a_child(self):
        self.take()
        ticket, plan = self.port.ticket("c1"), self.port.approved("c1")
        self.port.step_commit("c1", ticket, plan, str(self.repo), git(self.repo, "rev-parse", "HEAD").strip(), False)
        after = self.port.ticket("c1")
        self.assertEqual((after["state"], after["phase"]), ("open", "deliver"))  # waits for its handback
        self.port.write(lambda con, rec: __import__("harness.utils.plan.tickets", fromlist=["x"]).save(
            con, {**self.port.ticket("c1"), "state": "closed", "closeReason": "delivered"}))
        work.take(self.port, "c1", str(self.repo))  # a take on a new ticket keeps the role
        self.assertEqual(self.port.ticket("c1")["child"]["name"], "api")

    def test_a_child_of_a_unit_works_in_the_units_folder_with_its_test_command(self):
        repo = git_repo(self, {"services/api/a.py": "X = 1\n", "web/b.js": "1\n"})
        unit = {"repo": "https://github.com/me/shop", "path": "services/api", "verify": ["{python}", "-c", "pass"],
                "base": "develop"}
        Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": brief.brief(7, "pd-x", {**CARD, "unit": "api"},
                                                                              "session_p1", unit, rounds=3)}, "u1", str(repo)),
                           {}, ALLOW)
        work.take(self.port, "u1", str(repo / "web"))  # anywhere in the clone: the plan is rooted in the unit
        plan = self.port.approved("u1")
        self.assertEqual((plan["root"], plan["verify"], plan["services"]),
                         (f"{repo.as_posix()}/services/api", ["{python}", "-c", "pass"], ["api"]))
        from harness.utils.plan.verify import command_of
        self.assertEqual(command_of(plan, ["other"])[1:], ["-c", "pass"])
        bad = {**unit, "path": "nowhere"}
        Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": brief.brief(7, "pd-x", {**CARD, "unit": "api"},
                                                                              "session_p1", bad, rounds=3)}, "u2", str(repo)),
                           {}, ALLOW)
        with self.assertRaisesRegex(work.WorkError, "folder nowhere is not in this clone"):
            work.take(self.port, "u2", str(repo))

    def test_a_new_branch_starts_from_the_units_base(self):
        """A child's pull request into a base that is not the default branch holds only the child's commits."""
        git(self.repo, "switch", "-q", "-c", "release")
        (self.repo / "r.txt").write_text("on release only\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "release work")
        git(self.repo, "push", "-q", "origin", "release")
        git(self.repo, "switch", "-q", "work")
        self.assertEqual(work.switch(str(self.repo), "orch/p7/x", "release"), "new from origin/release")
        self.assertTrue((self.repo / "r.txt").is_file())
        git(self.repo, "switch", "-q", "work")
        self.assertEqual(work.switch(str(self.repo), "orch/p7/y", "nowhere"), "new from HEAD")
        self.assertFalse((self.repo / "r.txt").is_file())


if __name__ == "__main__":
    unittest.main()
