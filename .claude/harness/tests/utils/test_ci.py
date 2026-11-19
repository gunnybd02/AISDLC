"""Sessions part 5, harness ci (utils/orchestra/ci.py): the child's gate run again from the branch alone. A real
repository holds the plan branch (with its locked test) and the child's branch (its registration first, then its
work); a fake GitHub answers the child's issue. A branch that keeps every rule is green; each broken rule fails with
why, and a rule that cannot run fails as not checked."""
import json
import subprocess
import unittest

from harness.utils.orchestra import ci, issues, register
from harness.tests.e2e import git_repo

CARD = {"name": "api", "unit": "home", "goal": "List the orders of a user", "ac": ["GET /orders returns the orders"],
        "change": ["app/orders.py"], "tests": ["tests/test_orders.py"], "acTests": ["tests/test_orders_ac.py"]}
PLAN = {"id": 7, "sha": "f" * 64, "children": [CARD]}
URL = "https://github.com/o/r"
SECRET = "KEY = 'AKIA" + "ABCDEFGHIJKLMNOP'\n"


def git(repo, *args):
    """git in repo; its output."""
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


class CiTest(unittest.TestCase):
    def setUp(self):
        self.repo = git_repo(self, {"a.py": "X = 1\n"})
        _, self.body, sha = issues.issue_text(CARD, issues.block_of(PLAN, "pd-x", CARD, URL, "plan/p7"), 7)
        self.calls = []
        git(self.repo, "switch", "-q", "-c", "plan/p7")
        self.commit({"tests/test_orders_ac.py": "# locked\n"}, "Acceptance tests of plan 7, locked")
        git(self.repo, "switch", "-q", "-c", "orch/p7/api")
        record = {"format": register.RECORD_FORMAT, "plan": "pd-x", "child": "api", "branch": "orch/p7/api",
                  "repo": "o/r", "issue": 41, "issueSha": sha, "ticketSha256": "b" * 64, "planSha": "f" * 64}
        self.commit({".harness/register/api.json": json.dumps(record, indent=1, sort_keys=True) + "\n"},
                    "#41 api: register (issue x, ticket y)")
        self.commit({"app/orders.py": "ORDERS = []\n", "tests/test_orders.py": "# test\n"}, "#41 api: List orders")
        self.commit({".harness/handback/api.json": "{}\n"}, "#41 api: Handback of api (plan 7)")

    def commit(self, files, message):
        for rel, text in files.items():
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", message)

    def github(self, method, path, fields=None):
        self.calls.append((method, path))
        return {"number": 41, "body": self.body}

    def results(self, base="plan/p7", head="orch/p7/api"):
        return {rule: (ok, why) for rule, ok, why in ci.check(str(self.repo), base, head, self.github)}

    def failed(self, **kw):
        return {rule: why for rule, (ok, why) in self.results(**kw).items() if not ok}

    def test_a_branch_that_keeps_every_rule_is_green(self):
        """s4.ci.rules: every rule passes, read from the branch and the issue the registration names."""
        results = self.results()
        self.assertEqual(list(results), list(ci.RULES))
        self.assertEqual([rule for rule, (ok, _) in results.items() if not ok], [])
        self.assertEqual(self.calls, [("GET", "repos/o/r/issues/41")])  # one read of the issue the record names
        ok, text = ci.report(str(self.repo), "plan/p7", "orch/p7/api", self.github)
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
        ok, text = ci.report(str(self.repo), "plan/p7", "orch/p7/api", self.github)
        self.assertFalse(ok)
        self.assertTrue(text.endswith("Result: RED, 5 rule(s) failed: subjects, marks, secrets, scope, locked."))

    def test_code_before_the_registration_fails(self):
        record = (self.repo / ".harness" / "register" / "api.json").read_text(encoding="utf-8")
        git(self.repo, "switch", "-q", "plan/p7")
        git(self.repo, "branch", "-q", "-D", "orch/p7/api")
        git(self.repo, "switch", "-q", "-c", "orch/p7/api")
        self.commit({"app/orders.py": "ORDERS = []\n"}, "#41 api: List orders")
        failed = self.failed()  # no registration at all: nothing else can be read
        self.assertEqual(failed["registered"], "orch/p7/api holds no registration (.harness/register/api.json)")
        self.assertEqual(failed["scope"], "not checked: no registration names the issue")
        self.assertEqual((len(failed), self.calls), (len(ci.RULES), []))
        self.commit({".harness/register/api.json": record}, "#41 api: register late")
        self.assertEqual(self.failed(), {"registered": "orch/p7/api does not start with its registration: its first "
                                                       "commit over plan/p7 changes app/orders.py"})

    def test_an_edited_issue_a_wrong_base_or_head_fails(self):
        self.body = self.body.replace('"tests/test_orders.py"', '"tests/"')  # the block edited by hand
        failed = self.failed()
        self.assertIn("issue #41: its machine block does not match its own sha256", failed["issue"])
        self.assertEqual(failed["locked"], "not checked: the issue was not read")
        self.assertEqual(set(failed), {"issue", "base", "scope", "locked"})
        self.setUp()
        self.assertIn("work is not the plan branch plan/p7", self.failed(base="work")["base"])
        self.assertEqual(self.failed(head="feature")["branch"], "feature is no branch of a child (orch/p<plan>/<name>)")

    def test_the_start_commit_of_the_parent_waits_then_is_skipped(self):
        """s1.ci.waiting: the start commit alone is WAITING (exit 0); later the registration still comes first."""
        record = (self.repo / ".harness" / "register" / "api.json").read_text(encoding="utf-8")
        git(self.repo, "switch", "-q", "plan/p7")
        git(self.repo, "branch", "-q", "-D", "orch/p7/api")
        git(self.repo, "switch", "-q", "-c", "orch/p7/api")
        self.commit({".harness/notes/api/start.md": "# Start of api\n"}, "#41 api: start")
        ok, text = ci.report(str(self.repo), "plan/p7", "orch/p7/api", self.github)
        self.assertTrue(ok)
        self.assertEqual(text.splitlines()[1:], [f"WAIT: {ci.WAITING}.", "Result: WAITING, nothing to check yet."])
        self.assertEqual(self.calls, [])
        self.commit({".harness/register/api.json": record}, "#41 api: register (issue x, ticket y)")
        self.commit({"app/orders.py": "ORDERS = []\n"}, "#41 api: List orders")
        self.assertEqual(self.failed(), {})
        self.assertIn("registers api for issue #41", self.results()["registered"][1])

    def test_has_code_once_a_commit_follows_the_start_and_the_registration(self):
        """s5.ci.has-code: false for the start and the registration alone, true with a later commit."""
        record = (self.repo / ".harness" / "register" / "api.json").read_text(encoding="utf-8")
        self.assertTrue(ci.has_code(str(self.repo), "plan/p7", "orch/p7/api"))  # code and handback on it
        git(self.repo, "switch", "-q", "plan/p7")
        git(self.repo, "branch", "-q", "-D", "orch/p7/api")
        git(self.repo, "switch", "-q", "-c", "orch/p7/api")
        self.assertFalse(ci.has_code(str(self.repo), "plan/p7", "orch/p7/api"))  # nothing over the base
        self.commit({".harness/notes/api/start.md": "# Start of api\n"}, "#41 api: start")
        self.commit({".harness/register/api.json": record}, "#41 api: register (issue x, ticket y)")
        self.assertFalse(ci.has_code(str(self.repo), "plan/p7", "orch/p7/api"))
        self.commit({"app/orders.py": "ORDERS = []\n"}, "#41 api: List orders")
        self.assertTrue(ci.has_code(str(self.repo), "plan/p7", "orch/p7/api"))
        self.assertTrue(ci.has_code(str(self.repo), "plan/p7", "feature"))  # no child branch: the tests run
        self.assertTrue(ci.has_code(str(self.repo), "no-such-base", "orch/p7/api"))  # not readable: they run

    def test_check_and_has_code_judge_the_commit_under_test(self):
        """s2.ci.commit-under-test: live run 5 ran the tests of the registration commit after code was pushed."""
        registration = git(self.repo, "rev-parse", "HEAD~2").strip()  # under it: code, then the handback
        self.assertTrue(ci.has_code(str(self.repo), "plan/p7", "orch/p7/api"))  # the tip has code
        self.assertFalse(ci.has_code(str(self.repo), "plan/p7", "orch/p7/api", registration))
        results = {rule: (ok, why) for rule, ok, why in ci.check(str(self.repo), "plan/p7", "orch/p7/api", self.github,
                                                                  registration)}
        self.assertEqual([rule for rule, (ok, _) in results.items() if not ok], [])
        self.commit({"app/other.py": "1\n"}, "#41 api: out of scope")  # a later push on the tip
        self.assertIn("scope", [r for r, ok, _ in ci.check(str(self.repo), "plan/p7", "orch/p7/api", self.github) if not ok])
        ok, _ = ci.report(str(self.repo), "plan/p7", "orch/p7/api", self.github, registration)
        self.assertTrue(ok)  # the commit under test is judged, not the later tip


if __name__ == "__main__":
    unittest.main()
