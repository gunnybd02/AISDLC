"""Sessions part 5, the draft pull request (utils/orchestra/draft.py): for a plan with locked tests, spawn makes the
child's branch from the base with one start commit that adds its locked tests, opens one draft pull request into the
base (a fake GitHub here, a real origin), and gives the call that watches it."""
import json
import unittest

from harness.mcp.actions.orchestra import Spawn, Tickets
from harness.utils.contracts import ActionContext
from harness.utils.orchestra import draft, talk
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
        self.port.write(lambda con, rec: plan_tickets.save(con, {**self.port.ticket("s1"), "crew": {}, "drafts": {}}))
        self.github = FakeGitHub()
        Tickets().run(self.ctx_of(), {"into": str(tree(self, {}))})

    def ctx_of(self):
        return ActionContext({"plans": self.port, "session": lambda: "s1", "units": lambda: LOCKED_UNITS,
                              "github": self.github, "limits": lambda: {"children": 3, "rounds": 3}})

    def spawn(self):
        return Spawn().run(self.ctx_of(), {"name": "hello"})


class DraftTest(DraftScenario):
    def test_spawn_opens_one_draft_after_a_start_commit_and_gives_the_watch_call(self):
        """s6.start.tests: the start commit is cut from the base and adds the locked tests (the parent's copy, from
        the ledger); then one draft into the base, kept. No plan branch."""
        text = self.spawn()
        ref, into = f"orch/p{self.plan}/hello", "work"
        self.assertEqual(git(self.origin, "log", "--format=%s", f"{into}..{ref}").splitlines(), ["#41 hello: start"])
        self.assertEqual(git(self.origin, "show", "--name-only", "--format=", ref).split(),
                         ["orch-probe/test_hello_ac.py"])  # the locked test, nothing else (no .harness file)
        from harness.tests.utils.test_review import AC_TEST
        self.assertEqual(git(self.origin, "show", f"{ref}:orch-probe/test_hello_ac.py"), AC_TEST)
        self.assertNotIn(f"plan/p{self.plan}", git(self.origin, "branch", "--list"))
        self.assertIn("Issue #41: https://github.com/o/r/issues/41", git(self.origin, "log", "-1", "--format=%B", ref))
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

    def test_a_child_of_a_plan_without_locked_tests_gets_a_draft_into_its_base(self):
        """s2.start.empty: no lock and no issue: the empty start is "<name>: start" and the draft goes into the base."""
        from harness.tests.utils.test_review import LOCKED_UNITS
        from harness.utils.orchestra.issues import ISSUES
        from harness.utils.orchestra.locked import LOCK
        ticket = self.port.ticket("s1")
        self.port.write(lambda con, rec: plan_tickets.save(con, {**ticket, LOCK: {}, ISSUES: {}}))
        card = {"name": "hello", "goal": "Add a hello module", "change": ["hello.py"]}
        pr = draft.open_draft(self.port, "s1", card, LOCKED_UNITS["probe"], self.github)
        ref = f"orch/p{self.plan}/hello"
        self.assertEqual(git(self.origin, "log", "--format=%s", f"work..{ref}").splitlines(), ["hello: start"])
        self.assertEqual(git(self.origin, "show", "--name-only", "--format=", ref).split(), [])
        (_, _, fields), = self.github.pulls()
        self.assertEqual((fields["head"], fields["base"], fields["draft"]), (ref, "work", True))
        self.assertNotIn("issue", fields["body"])
        self.assertEqual(pr["number"], 5)

    def watch(self, response, number=5, repo="r"):
        """The hook's Act on the answer of the watch call in the parent's session."""
        from harness.assemble.engine.runner import Act
        from harness.utils.contracts import Event, Verdict
        event = Event("PostToolUse", draft.WATCH, {"owner": "o", "repo": repo, "pullNumber": number}, "s1", "/w", response)
        return Act(self.port).run(event, {}, Verdict("allow"))

    def started(self):
        from harness.mcp.actions.orchestra import Started
        return Started().run(self.ctx_of(), {"name": "hello", "sid": "session_child0001"})

    def test_started_waits_for_the_watch_the_hook_records(self):
        """s2.draft.watch: no draft, then an unwatched one, refuse started; the answer of the watch records it."""
        from harness.utils.contracts import ActionError
        with self.assertRaisesRegex(ActionError, r"hello has no draft pull request yet: run\('orchestra', 'spawn'"):
            self.started()
        self.spawn()
        with self.assertRaisesRegex(ActionError, r"watch the draft pull request #5 of hello first"):
            self.started()
        self.assertEqual(self.watch("Subscribed.", number=6), [])  # another pull request: not this child's draft
        self.assertEqual(self.watch("Subscribed.", repo="other"), [])
        other = self.watch("A Claude agent is already watching this PR; this session will not receive its events.")
        self.assertIn("watched by another session or agent", other[0])
        self.assertNotIn("watched", self.port.ticket("s1")[draft.DRAFTS]["hello"])
        self.assertIn("recorded your watch of the draft pull request #5 of hello", self.watch({"ok": True})[0])
        self.assertIsInstance(self.port.ticket("s1")[draft.DRAFTS]["hello"]["watched"], int)
        self.assertIn("runs in session session_child0001", self.started())

    def test_the_brief_and_the_record_of_the_child_name_its_draft(self):
        """s1.child.pr: spawn opens the draft first; the brief says it, and the child's role keeps it."""
        from harness.utils.orchestra import child
        text = self.spawn()
        prompt = json.loads(text[text.index("\n{") + 1:])["prompt"]
        self.assertIn("Your draft pull request is #5 (https://github.com/o/r/pull/5)", prompt)
        self.assertEqual(child.parse(prompt)["record"]["pr"],
                         {"repo": "o/r", "number": 5, "url": "https://github.com/o/r/pull/5"})


class ReadyTest(LockedScenario):
    """accept makes the draft ready: GraphQL first, the cloud proxy's route when GraphQL is refused (live run 2)."""

    def refusing(self, *refused):
        calls = []

        def github(method, path, fields=None):
            calls.append((method, path))
            if any(path.startswith(r) for r in refused):
                raise draft.GitHubError(f"gh api {method} {path}: HTTP 403")
            return {}
        return github, calls

    def test_a_refused_graphql_call_falls_back_to_the_route(self):
        """s1.draft.ready-fallback: the draft is made ready through repos/o/r/pulls/5/ccr/ready_for_review."""
        github, calls = self.refusing("graphql")
        pr = draft.ready(self.port.ticket("s1"), "hello", github)
        self.assertEqual(pr, {"number": 5, "html_url": "https://github.com/o/r/pull/5"})
        self.assertEqual(calls, [("POST", "graphql"), ("POST", "repos/o/r/pulls/5/ccr/ready_for_review")])
        github, calls = self.refusing()
        draft.ready(self.port.ticket("s1"), "hello", github)
        self.assertEqual(calls, [("POST", "graphql")])  # GraphQL answers: no second call

    def test_both_refused_raise_and_accept_records_nothing(self):
        """s1.draft.ready-refused: the route's error comes up; accept refuses and the child is not accepted."""
        from harness.utils.orchestra import review
        github, calls = self.refusing("graphql", "repos/")
        with self.assertRaisesRegex(draft.GitHubError, "ccr/ready_for_review"):
            draft.ready(self.port.ticket("s1"), "hello", github)
        self.hand_back()
        self.assertIn("Green", self.check())
        with self.assertRaisesRegex(review.ReviewError, "was not merged"):
            review.accept(self.port, "s1", "hello", LOCKED_UNITS, github)
        entry = self.port.ticket("s1")["crew"]["hello"]
        self.assertNotEqual(entry["state"], "accepted")
        self.assertNotIn("pr", entry)


class SayTest(unittest.TestCase):
    """A child whose brief names its draft: question and handback reach the parent as comments the harness posts."""
    PR = {"repo": "o/r", "number": 5, "url": "https://github.com/o/r/pull/5"}
    REPORT = {"changed": ["app/orders.py lists orders"], "checked": ["tests pass"], "notChecked": [],
              "risks": ["paging is not done"], "testsChanged": []}

    def setUp(self):
        from harness.assemble.engine.ports import LedgerPort
        from harness.assemble.engine.runner import Act
        from harness.utils.contracts import Event, Verdict
        from harness.utils.orchestra import brief, work
        from harness.tests.e2e import copy_tree, git_repo
        from harness.tests.utils.test_work import CARD
        self.port, self.repo, origin = LedgerPort(copy_tree(self)), git_repo(self, {"a.py": "X = 1\n"}), tree(self, {})
        git(origin, "init", "-q", "--bare")
        git(self.repo, "remote", "add", "origin", str(origin))
        self.calls = []
        for sid, pr in (("c1", self.PR), ("c2", None)):
            prompt = brief.brief(7, "pd-x", CARD, "session_p1", rounds=3, pr=pr)
            Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": prompt}, sid, str(self.repo)), {},
                               Verdict("allow"))
        work.take(self.port, "c1", str(self.repo))

    def github(self, method, path, fields=None):
        self.calls.append((method, path, dict(fields or {})))
        return {"id": 900 + len(self.calls), "html_url": f"https://github.com/o/r/pull/5#issuecomment-{len(self.calls)}"}

    def ctx(self, sid="c1"):
        allow = __import__("harness.utils.contracts", fromlist=["Verdict"]).Verdict("allow")
        return ActionContext({"plans": self.port, "session": lambda: sid, "commit_judge": lambda *a: allow,
                              "git_judge": lambda *a: allow, "store": lambda: "", "github": self.github})

    def test_question_and_handback_are_posted_on_the_draft_and_recorded(self):
        """s1.child.comment: each one comment with the harness marker; the child's ledger keeps its id and hash."""
        from harness.mcp.actions.orchestra import Handback, Question
        text = Question().run(self.ctx(), {"question": "Which status code for a closed account?"})
        self.assertIn("Question 1 is the comment https://github.com/o/r/pull/5#issuecomment-1 on your draft", text)
        Handback().run(self.ctx(), self.REPORT)
        (m1, p1, f1), (m2, p2, f2) = self.calls
        self.assertEqual((m1, p1, p2), ("POST", "repos/o/r/issues/5/comments", "repos/o/r/issues/5/comments"))
        self.assertEqual(f1["body"].split("\n\n")[:2], ["**Question of api** (plan 7)",
                                                         "Which status code for a closed account?"])
        meta = talk.read({"body": f1["body"]})
        self.assertEqual((meta["kind"], meta["child"], meta["from"], meta["n"]), ("question", "api", "child", 1))
        self.assertIn("Changed: app/orders.py lists orders\n\nChecked: tests pass\n\nNot checked: none\n\n"
                      "Risks: paging is not done", f2["body"])
        rows = self.port.rows("SELECT key, target, text FROM pl_notes WHERE kind = 'talk.said' ORDER BY rowid")
        self.assertEqual([r["key"] for r in rows], ["question", "handback"])
        self.assertEqual(json.loads(rows[0]["text"])["id"], 901)
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
