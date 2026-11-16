"""orchestra part 2: a child takes its card (the card plan opens by the parent's grant, no form, on its branch), pushes
its own branch, asks, and hands back: the receipt is written by harness code, committed and pushed with the branch.
A real repository with a bare origin."""
import json
import subprocess
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.utils.contracts import Event, Verdict
from harness.utils.orchestra import brief, work
from harness.tests import tree
from harness.tests.e2e import copy_tree, git_repo

CARD = {"name": "api", "unit": "home", "goal": "List the orders of a user",
        "ac": ["GET /orders returns the user's orders"], "change": ["app/orders.py"], "tests": ["tests/test_orders.py"]}
REPORT = {"changed": ["app/orders.py lists orders"], "checked": ["tests/test_orders.py passes"], "notChecked": [],
          "risks": ["paging is not done"], "testsChanged": [{"test": "tests/test_orders.py", "why": "new"}]}
ALLOW = Verdict("allow")


def git(repo, *args):
    """The output of git in repo."""
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


class WorkTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(copy_tree(self, {"project.json": json.dumps({"name": "t"})}))
        self.repo = git_repo(self, {"a.py": "X = 1\n"})
        self.origin = tree(self, {})
        git(self.origin, "init", "-q", "--bare")
        git(self.repo, "remote", "add", "origin", str(self.origin))
        Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": brief.brief(7, "pd-x", CARD, "session_p1")},
                                 "c1", str(self.repo)), {}, ALLOW)

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

    def test_a_question_is_kept_and_says_whom_to_send_it(self):
        text = work.ask(self.port, "c1", "Which status code for a closed account?")
        self.assertIn("send_message to the orchestrator session_p1", text)
        self.assertEqual(self.port.ticket("c1")["asks"][0]["n"], 1)
        with self.assertRaisesRegex(work.WorkError, "one to 400"):
            work.ask(self.port, "c1", " ")

    def test_the_handback_receipt_is_committed_and_pushed(self):
        self.take()
        with self.assertRaisesRegex(work.WorkError, "changed names at least one point"):
            work.handback(self.port, "c1", {**REPORT, "changed": []}, lambda *a: ALLOW, lambda *a: ALLOW)
        (self.repo / "scratch.txt").write_text("left over\n", encoding="utf-8")
        text = work.handback(self.port, "c1", REPORT, lambda *a: ALLOW, lambda *a: ALLOW, store_on=True)
        self.assertIn('"handed back orch/p7/api', text)
        self.assertIn("Save your ledger to the store first: run('ledger', 'export', {reason: 'handback'})", text)
        receipt = json.loads(git(self.origin, "show", "orch/p7/api:.harness/handback/api.json"))
        self.assertEqual((receipt["name"], receipt["plan"], receipt["parent"], receipt["verify"]),
                         ("api", 7, "session_p1", "missing"))
        self.assertEqual(receipt["report"]["risks"], ["paging is not done"])
        self.assertEqual(receipt["uncommitted"], ["scratch.txt"])
        self.assertIn("p7.api.ac1", receipt["behaviours"])
        self.assertEqual(self.port.ticket("c1")["handback"]["sha"], git(self.repo, "rev-parse", "HEAD").strip())
        with self.assertRaisesRegex(work.WorkError, "commit is stopped"):
            work.handback(self.port, "c1", REPORT, lambda *a: Verdict("refuse", "a secret"), lambda *a: ALLOW)

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
                                                                              "session_p1", unit)}, "u1", str(repo)),
                           {}, ALLOW)
        work.take(self.port, "u1", str(repo / "web"))  # anywhere in the clone: the plan is rooted in the unit
        plan = self.port.approved("u1")
        self.assertEqual((plan["root"], plan["verify"], plan["services"]),
                         (f"{repo.as_posix()}/services/api", ["{python}", "-c", "pass"], ["api"]))
        from harness.utils.plan.verify import command_of
        self.assertEqual(command_of(plan, ["other"])[1:], ["-c", "pass"])
        bad = {**unit, "path": "nowhere"}
        Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": brief.brief(7, "pd-x", {**CARD, "unit": "api"},
                                                                              "session_p1", bad)}, "u2", str(repo)),
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
