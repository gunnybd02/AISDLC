"""Sessions part 5, harness ci (utils/orchestra/ci.py): the child's gate run again from the branch and its issue alone.
A real repository holds the plan branch (with its locked test) and the child's branch (the parent's empty start
commit, then the child's work); a fake GitHub answers the child's issue and its comments, where the registration is.
A branch that keeps every rule is green; each broken rule fails with why, and a rule that cannot run fails as not
checked."""
import json
import subprocess
import unittest

from harness.utils.git.github import GitHubError
from harness.utils.orchestra import ci, issues, register, talk
from harness.tests.e2e import git_repo

CARD = {"name": "api", "unit": "home", "goal": "List the orders of a user", "ac": ["GET /orders returns the orders"],
        "change": ["app/orders.py"], "tests": ["tests/test_orders.py"], "acTests": ["tests/test_orders_ac.py"]}
PLAN = {"id": 7, "sha": "f" * 64, "children": [CARD]}
URL = "https://github.com/o/r"
SECRET = "KEY = 'AKIA" + "ABCDEFGHIJKLMNOP'\n"
COMMENTS = "repos/o/r/issues/41/comments?per_page=100"


def git(repo, *args):
    """git in repo; its output."""
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def registration(sha, n=801, **change):
    """The registration comment a child's harness posts on its issue (register.on_issue)."""
    meta = {"kind": "register", "child": "api", "plan": 7, "from": "child", "format": register.RECORD_FORMAT,
            "draft": "pd-x", "branch": "orch/p7/api", "issueSha": sha, "ticketSha256": "b" * 64, "planSha": "f" * 64,
            **change}
    return {"id": n, "html_url": f"{URL}/issues/41#c{n}",
            "body": "**Register of api** (plan 7)\n\nRegistered.\n\n" + talk.MARK.format(meta=json.dumps(meta))}


class CiTest(unittest.TestCase):
    def setUp(self):
        self.repo = git_repo(self, {"a.py": "X = 1\n"})
        _, self.body, self.sha = issues.issue_text(CARD, issues.block_of(PLAN, "pd-x", CARD, URL, "plan/p7"), 7)
        self.comments, self.calls = [registration(self.sha)], []
        git(self.repo, "switch", "-q", "-c", "plan/p7")
        self.commit({"tests/test_orders_ac.py": "# locked\n"}, "Acceptance tests of plan 7, locked")
        git(self.repo, "switch", "-q", "-c", "orch/p7/api")
        self.commit({}, "#41 api: start\n\nThe orchestrator made this branch from plan/p7.")
        self.commit({"app/orders.py": "ORDERS = []\n", "tests/test_orders.py": "# test\n"}, "#41 api: List orders")

    def commit(self, files, message):
        for rel, text in files.items():
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", message)

    def github(self, method, path, fields=None):
        self.calls.append((method, path))
        if path == "repos/o/r/issues/41":
            return {"number": 41, "body": self.body}
        if path == COMMENTS:
            return list(self.comments)
        raise GitHubError(f"gh api {method} {path}: HTTP 404")

    def results(self, base="plan/p7", head="orch/p7/api", slug="o/r"):
        return {rule: (ok, why) for rule, ok, why in ci.check(str(self.repo), base, head, self.github, slug=slug)}

    def failed(self, **kw):
        return {rule: why for rule, (ok, why) in self.results(**kw).items() if not ok}

    def fresh_branch(self):
        """The child's branch again from the plan branch, with nothing on it."""
        git(self.repo, "switch", "-q", "plan/p7")
        git(self.repo, "branch", "-q", "-D", "orch/p7/api")
        git(self.repo, "switch", "-q", "-c", "orch/p7/api")

    def test_a_branch_that_keeps_every_rule_is_green(self):
        """s4.ci.rules: every rule passes, read from the branch, the issue its start names and its comments."""
        results = self.results()
        self.assertEqual(list(results), list(ci.RULES))
        self.assertEqual([rule for rule, (ok, _) in results.items() if not ok], [])
        self.assertEqual(self.calls, [("GET", COMMENTS), ("GET", "repos/o/r/issues/41")])
        self.assertEqual(results["registered"][1], "comment 801 on issue #41 registers api for its plan")
        ok, text = ci.report(str(self.repo), "plan/p7", "orch/p7/api", self.github, slug="o/r")
        self.assertTrue(ok)
        self.assertEqual(text.splitlines()[0], "harness ci: orch/p7/api into plan/p7")
        self.assertIn("PASS subjects: every commit starts '#41 api: '", text)
        self.assertTrue(text.endswith("Result: GREEN, every rule passed."))

    def test_each_broken_rule_fails_with_why(self):
        self.commit({"app/orders.py": SECRET}, "Add a key\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
        self.commit({"app/other.py": "1\n", "tests/test_orders_ac.py": "# changed\n"}, "#41 api: more")
        failed = self.failed()
        self.assertEqual(set(failed), {"subjects", "marks", "secrets", "scope", "locked"})
        self.assertIn("these commits do not start '#41 api: '", failed["subjects"])
        self.assertIn("AI marks in", failed["marks"])
        self.assertIn("app/orders.py holds", failed["secrets"])
        self.assertEqual(failed["scope"], "outside the scope of the issue: app/other.py, tests/test_orders_ac.py")
        self.assertEqual(failed["locked"], "locked acceptance tests changed: tests/test_orders_ac.py")
        ok, text = ci.report(str(self.repo), "plan/p7", "orch/p7/api", self.github, slug="o/r")
        self.assertFalse(ok)
        self.assertTrue(text.endswith("Result: RED, 5 rule(s) failed: subjects, marks, secrets, scope, locked."))

    def test_the_issue_comes_from_the_start_subject_and_the_registration_from_its_comments(self):
        """s2.ci.issue-from-subject: no registration, one for another plan or issue block, or a start that names
        another issue fails; a later registration, the orchestrator's or another child's, does not count."""
        self.comments = []
        self.assertEqual(self.failed(), {"registered": "issue #41 holds no registration comment of api"})
        self.comments = [registration(self.sha, **{"from": "orchestrator"}), registration(self.sha, child="web")]
        self.assertEqual(self.failed(), {"registered": "issue #41 holds no registration comment of api"})
        self.comments = [registration(self.sha, planSha="e" * 64), registration(self.sha, n=802)]  # the oldest counts
        self.assertEqual(self.failed(), {"registered": "the registration is for another plan"})
        self.comments = [registration("0" * 64)]
        failed = self.failed()
        self.assertIn("issue #41: its block is not the one the registration names", failed["issue"])
        self.assertEqual(set(failed), {"issue", "base", "scope", "locked"})  # the block is not trusted
        self.comments = [registration(self.sha, branch="orch/p7/web")]
        self.assertIn("the registration orch/p7/web", self.failed()["branch"])
        self.comments = [registration(self.sha)]
        self.fresh_branch()
        self.commit({}, "#42 api: start")  # another issue: GitHub knows no #42 here
        self.commit({"app/orders.py": "ORDERS = []\n"}, "#42 api: List orders")
        failed = self.failed()
        self.assertIn("issue #42 cannot be read", failed["issue"])
        self.assertIn("not checked: the comments of issue #42 cannot be read", failed["registered"])

    def test_no_start_commit_or_no_repository_stops_the_rules(self):
        """s2.ci.issue-from-subject: a start that changes a file is no start; with no start the issue is unknown."""
        self.fresh_branch()
        self.commit({"app/orders.py": "ORDERS = []\n"}, "#41 api: start")
        failed = self.failed()
        self.assertEqual(failed["issue"], "no start commit '#<issue> api: start' over plan/p7 names the issue")
        self.assertEqual(failed["scope"], "not checked: no start commit names the issue")
        self.assertEqual((len(failed), self.calls), (len(ci.RULES), []))
        self.setUp()
        self.assertEqual(self.failed(slug="")["issue"], "not checked: the repository on GitHub is not known (--repo)")
        git(self.repo, "remote", "add", "origin", URL)  # the slug is read from the origin's URL
        self.assertEqual(self.failed(slug=""), {})

    def test_a_harness_file_on_the_branch_is_outside_the_scope(self):
        """s2.ci.issue-from-subject: the talk is in comments, so no .harness file is the child's own any more."""
        self.commit({".harness/notes/api/question-1.md": "# Question\n"}, "#41 api: Question 1 of api (plan 7)")
        self.commit({".harness/handback/api.json": "{}\n"}, "#41 api: Handback of api (plan 7)")
        self.assertEqual(self.failed(), {"scope": "outside the scope of the issue: .harness/handback/api.json, "
                                                  ".harness/notes/api/question-1.md"})

    def test_an_edited_issue_a_wrong_base_or_head_fails(self):
        self.body = self.body.replace('"tests/test_orders.py"', '"tests/"')  # the block edited by hand
        failed = self.failed()
        self.assertIn("issue #41: its machine block does not match its own sha256", failed["issue"])
        self.assertEqual(failed["locked"], "not checked: the issue was not read")
        self.assertEqual(set(failed), {"issue", "base", "scope", "locked"})
        self.setUp()
        self.assertIn("work is not the plan branch plan/p7", self.failed(base="work")["base"])
        self.assertEqual(self.failed(head="feature")["branch"], "feature is no branch of a child (orch/p<plan>/<name>)")

    def test_a_branch_whose_commits_change_no_file_waits(self):
        """s1.ci.waiting: the start and empty signal commits alone are WAITING (exit 0), and nothing is read."""
        self.fresh_branch()
        self.commit({}, "#41 api: start")
        self.commit({}, "#41 api: Registration of api failed (plan 7)")
        ok, text = ci.report(str(self.repo), "plan/p7", "orch/p7/api", self.github, slug="o/r")
        self.assertTrue(ok)
        self.assertEqual(text.splitlines()[1:], [f"WAIT: {ci.WAITING}.", "Result: WAITING, nothing to check yet."])
        self.assertEqual(self.calls, [])
        self.commit({"app/orders.py": "ORDERS = []\n"}, "#41 api: List orders")
        self.assertEqual(self.failed(), {})

    def test_has_code_once_a_commit_changes_a_file(self):
        """s5.ci.has-code: false while every commit is empty, true once one changes a file."""
        self.assertTrue(ci.has_code(str(self.repo), "plan/p7", "orch/p7/api"))
        self.fresh_branch()
        self.assertFalse(ci.has_code(str(self.repo), "plan/p7", "orch/p7/api"))  # nothing over the base
        self.commit({}, "#41 api: start")
        self.commit({}, "#41 api: Question 1 of api (plan 7)")
        self.assertFalse(ci.has_code(str(self.repo), "plan/p7", "orch/p7/api"))
        self.commit({"app/orders.py": "ORDERS = []\n"}, "#41 api: List orders")
        self.assertTrue(ci.has_code(str(self.repo), "plan/p7", "orch/p7/api"))
        self.assertTrue(ci.has_code(str(self.repo), "plan/p7", "feature"))  # no child branch: the tests run
        self.assertTrue(ci.has_code(str(self.repo), "no-such-base", "orch/p7/api"))  # not readable: they run

    def test_check_and_has_code_judge_the_commit_under_test(self):
        """s2.ci.commit-under-test: live run 5 ran the tests of an older commit after code was pushed."""
        start, code = git(self.repo, "rev-parse", "HEAD~1").strip(), git(self.repo, "rev-parse", "HEAD").strip()
        self.assertFalse(ci.has_code(str(self.repo), "plan/p7", "orch/p7/api", start))
        self.assertTrue(ci.has_code(str(self.repo), "plan/p7", "orch/p7/api", code))
        self.commit({"app/other.py": "1\n"}, "#41 api: out of scope")  # a later push on the tip
        self.assertIn("scope", [r for r, ok, _ in ci.check(str(self.repo), "plan/p7", "orch/p7/api", self.github,
                                                           slug="o/r") if not ok])
        results = ci.check(str(self.repo), "plan/p7", "orch/p7/api", self.github, code, "o/r")
        self.assertEqual([rule for rule, ok, _ in results if not ok], [])
        ok, _ = ci.report(str(self.repo), "plan/p7", "orch/p7/api", self.github, code, "o/r")
        self.assertTrue(ok)  # the commit under test is judged, not the later tip


if __name__ == "__main__":
    unittest.main()
