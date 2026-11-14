"""h9.step-done: the harness commits a plan step by step: only after what the step owes is proven, only the step's
files, never a secret or on a protected branch; the last step delivers a home plan with no form; a skip gives a step
up; a write in deliver goes back to execute for a fix."""
import json
import unittest

from harness.assemble.engine.config import Config
from harness.assemble.engine.ports import LedgerPort
from harness.utils.contracts import YES
from harness.utils.git.run import git
from harness.utils.plan.approval import approvals
from harness.utils.plan.steps import StepError, step_done, step_skip
from harness.utils.plan.verify import verify
from tests.e2e import copy_tree, git_repo

TEST = "import unittest\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\n"
LIGHT = {"title": "Set the value", "what": ["X becomes 2"], "files": ["a.py"], "tests": ["test_a.py"]}
STEPS = {**LIGHT, "files": [], "tests": [], "steps": [
    {"commit": "Set A", "points": ["a"], "files": ["a.py"], "tests": ["test_a.py"],
     "behaviors": [{"id": "sets-a", "what": "a is 2", "how": "unit test", "why": "w", "test": "test_a.py"}]},
    {"commit": "Set B", "points": ["b"], "files": ["lib/*.py"]}]}


class StepsTest(unittest.TestCase):
    def setUp(self):
        self.claude_dir = copy_tree(self, {"project.json": json.dumps(
            {"name": "t", "verify": ["{python}", "-m", "unittest", "discover", "-s", "."]})})
        self.repo = git_repo(self, {"a.py": "X = 1\n", "test_a.py": TEST, "other.py": "Y = 1\n", "lib/b.py": "B = 1\n"})
        self.port = LedgerPort(self.claude_dir)

    def approve(self, items):
        from harness.utils.plan import desk
        normal = {**desk.normalize(desk.clean(items)), "root": str(self.repo)}
        plan_id, _, q = self.port.present(normal, sid="s1")
        approvals(self.port, "s1", {q: YES})
        self.plan_id = plan_id

    def verify(self):
        return verify(self.port, Config.load(self.claude_dir).verify, self.plan_id)

    def write(self, name, text):
        (self.repo / name).write_text(text, encoding="utf-8")

    def refused(self, why, message="Set X"):
        with self.assertRaises(StepError) as caught:
            step_done(self.port, "s1", message)
        self.assertIn(why, str(caught.exception))

    def subjects(self):
        return git(self.repo, "log", "--format=%s").split("\n")[:-1]

    def test_a_light_plan_is_one_step_committed_alone_then_delivered(self):
        self.approve(LIGHT)
        self.write("a.py", "X = 2\n")
        self.write("other.py", "Y = 2\n")  # changed, staged even, but no file of the plan
        git(self.repo, "add", "other.py")
        self.verify()
        self.assertIn("plan is delivered and its ticket is closed", step_done(self.port, "s1", "Set X"))
        self.assertEqual(git(self.repo, "show", "--name-only", "--format=%s", "HEAD").split(), ["Set", "X", "a.py"])
        self.assertIn("other.py", git(self.repo, "diff", "--cached", "--name-only"))
        ticket = self.port.ticket("s1")
        self.assertEqual((ticket["state"], ticket["closeReason"], len(ticket["commits"])), ("closed", "delivered", 1))
        self.refused("no plan in force")

    def test_steps_commit_one_by_one_and_the_last_delivers(self):
        self.approve(STEPS)
        self.write("a.py", "X = 2\n")
        self.write("lib/b.py", "B = 2\n")
        self.verify()
        self.refused("step-other-files: lib/b.py")
        git(self.repo, "checkout", "--", "lib/b.py")
        self.verify()
        self.assertIn("Step 1 is done; step 2 of 2 is open", step_done(self.port, "s1", "Set A"))
        self.write("lib/b.py", "B = 2\n")
        self.refused("changed after the last verify: lib/b.py")
        self.verify()
        self.assertIn("plan is delivered", step_done(self.port, "s1", "Set B"))
        self.assertEqual(self.subjects()[:2], ["Set B", "Set A"])
        self.assertEqual(len(self.port.rows("SELECT 1 FROM rec_commits")), 2)

    def test_what_a_step_owes(self):
        self.approve({**STEPS, "steps": [{**STEPS["steps"][0], "behaviors": [
            {"id": "sets-a", "what": "a is 2", "how": "h", "why": "w", "test": "test_new.py"}]}, STEPS["steps"][1]]})
        self.write("a.py", "X = 2\n")
        self.verify()
        self.refused("test_new.py is not written yet")
        self.approve({**STEPS, "steps": [{**STEPS["steps"][0], "behaviors": [
            {"id": "sets-a", "what": "a is 2", "how": "h", "why": "w"}]}, STEPS["steps"][1]]})
        self.verify()
        self.refused("has no test")

    def test_no_commit_without_a_green_verify_of_the_current_files(self):
        self.approve(LIGHT)
        self.write("a.py", "X = 2\n")
        self.refused("no green verify")
        self.write("test_a.py", TEST.replace("pass", "self.fail()"))
        self.verify()
        self.refused("no green verify")
        self.write("test_a.py", TEST)
        self.verify()
        self.write("a.py", "X = 3\n")
        self.refused("changed after the last verify: a.py")

    def test_no_commit_of_a_secret_or_on_a_protected_branch(self):
        self.approve(LIGHT)
        self.write("a.py", "KEY = 'AKIA" + "ABCDEFGHIJKLMNOP'\n")
        self.verify()
        self.refused("a.py holds an AWS access key")
        self.write("a.py", "X = 2\n")
        self.verify()
        git(self.repo, "checkout", "-q", "-b", "main")
        self.refused("step-protected-branch: main")
        self.assertEqual(git(self.repo, "rev-list", "--count", "HEAD").strip(), "1")

    def test_refusals_before_anything(self):
        self.approve(LIGHT)
        self.refused("step-no-message", message="  ")
        self.verify()
        self.refused("step-nothing-to-commit")
        git(self.repo, "commit", "--allow-empty", "-q", "-m", "moved")
        self.write("a.py", "X = 2\n")
        self.refused("repository moved")

    def test_a_skip_gives_the_step_up_and_a_write_in_deliver_goes_back_for_a_fix(self):
        self.approve(STEPS)
        self.write("a.py", "X = 2\n")
        with self.assertRaises(StepError):
            step_skip(self.port, "s1", "not needed")  # plan files are changed
        git(self.repo, "checkout", "--", "a.py")
        self.assertIn("step 2 is open", step_skip(self.port, "s1", "not needed"))
        self.assertEqual([r["op"] for r in self.port.rows("SELECT op FROM pl_behaviors ORDER BY rowid")], ["add", "skip"])
        self.assertIn("the ticket is in Deliver", step_skip(self.port, "s1", "nor this"))
        self.assertEqual(self.port.ticket("s1")["phase"], "deliver")
        self.port.back("s1")
        self.assertEqual((self.port.ticket("s1")["phase"], self.port.ticket("s1")["backs"]), ("execute", 1))

    def test_the_hook_sends_a_write_in_deliver_back_to_execute(self):
        from harness.assemble.engine.runner import Act
        from harness.gear.translate.place import Places
        from harness.utils.contracts import Event, Verdict
        self.approve(LIGHT)
        step_skip(self.port, "s1", "done elsewhere")
        self.assertEqual(self.port.ticket("s1")["phase"], "deliver")
        other = Event("PostToolUse", "Write", {"file_path": str(self.repo / "other.py")}, "s1", str(self.repo))
        Act(self.port).run(other, {**Places().translate(other), "plan": self.port.approved("s1")}, Verdict("allow"))
        self.assertEqual(self.port.ticket("s1")["phase"], "deliver")  # a write outside the plan keeps deliver
        write = Event("PostToolUse", "Write", {"file_path": str(self.repo / "a.py")}, "s1", str(self.repo))
        Act(self.port).run(write, {**Places().translate(write), "plan": self.port.approved("s1")}, Verdict("allow"))
        self.assertEqual(self.port.ticket("s1")["phase"], "execute")


if __name__ == "__main__":
    unittest.main()
