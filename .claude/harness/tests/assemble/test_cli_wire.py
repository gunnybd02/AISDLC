"""h16.cli-doors: from a terminal, verify runs the tests of the session's plan (lock, ledger copy, timeout) and keeps
the receipt; add file / add test / add drop-file / add retire-test / behaviors widen or shrink the plan with chained
rows, each refused with why; step_done then reads them."""
import json
import os
import unittest
import unittest.mock

from harness.assemble.engine.cli_wire import run_cli
from harness.assemble.engine.ports import LedgerPort
from harness.utils.contracts import YES
from harness.utils.plan import desk, tickets
from harness.utils.plan.approval import approvals
from harness.utils.plan.steps import StepError, step_done
from harness.tests import entry_of
from harness.tests.e2e import copy_tree, git_repo, run

TEST = "import unittest\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\n"
PLAN = {"title": "Set the value", "what": ["X becomes 2"], "files": ["a.py"], "tests": ["test_a.py"], "steps": [
    {"commit": "Set A", "points": ["a"], "files": ["a.py"], "tests": ["test_a.py"],
     "behaviors": [{"id": "sets-a", "what": "a is 2", "how": "unit test", "why": "w"}]}],
    "services": ["agent-code"], "checks": ["c"], "assumptions": ["a"], "notDoing": ["n"], "risks": ["r"]}


class CliTest(unittest.TestCase):
    def setUp(self):
        self.claude_dir = copy_tree(self)
        self.repo = git_repo(self, {"a.py": "X = 1\n", "test_a.py": TEST, "notes.md": "n\n"})
        self.port = LedgerPort(self.claude_dir)
        items = {**desk.normalize(desk.clean(PLAN)), "root": str(self.repo),
                 "verify": ["{python}", "-m", "unittest", "discover", "-s", "."]}  # set by the server from its repo
        _, _, q = self.port.present(items, sid="s1")
        approvals(self.port, "s1", {q: YES})

    def cli(self, *argv):
        return run_cli(["--session", "s1", *argv], self.claude_dir)

    def path(self, name):
        return str(self.repo / name)

    def test_verify_keeps_a_receipt_and_says_green_or_red(self):
        (self.repo / "a.py").write_text("X = 2\n", encoding="utf-8")
        code, out = self.cli("verify")
        self.assertEqual(code, 0, out)
        self.assertTrue(out.startswith("Verify green (exit 0): 1 changed file(s)"), out)
        self.assertEqual(self.port.receipt(self.port.approved("s1"))["ok"], 1)
        code, out = self.cli("verify", "--", "python3", "-c", "import sys; sys.exit(3)")
        self.assertEqual((code, out.split(":")[0]), (1, "Verify RED (exit 3)"))
        code, out = self.cli("verify", "--timeout", "1", "--", "python3", "-c", "import time; time.sleep(5)")
        self.assertIn("RED (exit 124)", out)
        self.assertIn("RED (exit 127)", self.cli("verify", "--", "no-such-program-x")[1])
        self.assertEqual(self.cli("verify", "--timeout", "0")[0], 1)

    def test_the_tests_get_no_ledger(self):
        self.port.touch_session("s1")
        code, out = self.cli("verify", "--", "python3", "-c", "import os; print(os.environ.get('HARNESS_DB', 'none'))")
        self.assertEqual(code, 0, out)
        self.assertEqual(out.splitlines()[-1], "none")  # a test that records builds its own home

    def test_add_file_widens_the_plan_and_each_door_refuses_with_why(self):
        self.assertEqual(self.cli("add", "file", self.path("notes.md"), "--behavior", "s1.sets-a", "--why", "docs")[0], 0)
        self.assertIn(("add", "notes.md"), self.port.approved("s1")["grants"])
        for argv, why in ((("add", "file", "notes.md", "--behavior", "s1.sets-a", "--why", "w"), "absolute"),
                          (("add", "file", self.path("x.md"), "--behavior", "nope", "--why", "w"), "no behaviour"),
                          (("add", "file", self.path("x.md"), "--behavior", "s1.sets-a", "--why", ""), "one line"),
                          (("add", "file", "/elsewhere/x.md", "--behavior", "s1.sets-a", "--why", "w"), "outside"),
                          (("add", "file", self.path(""), "--behavior", "s1.sets-a", "--why", "w"), "folder")):
            with self.subTest(why=why):
                code, out = self.cli(*argv)
                self.assertEqual(code, 1)
                self.assertIn(why, out)
        self.assertEqual(run_cli(["add", "file", self.path("x.md"), "--behavior", "b", "--why", "w"],
                                 self.claude_dir)[0], 1)  # no session

    def test_a_child_cannot_add_an_acceptance_test_it_is_judged_by(self):
        """s3.child.locked: in a child session, add file and add test refuse a locked acceptance test of its card."""
        def as_child(con, rec):
            fresh = tickets.latest(con, "s1")
            tickets.save(con, {**fresh, "child": {"name": "api", "plan": 7, "card": {"acTests": ["test_ac.py"]}}})
        self.port.write(as_child)
        (self.repo / "test_ac.py").write_text(TEST, encoding="utf-8")
        for argv in (("add", "file", self.path("test_ac.py"), "--behavior", "s1.sets-a", "--why", "w"),
                     ("add", "test", self.path("test_ac.py"), "--behavior", "s1.sets-a", "--what", "AC1: a is 2")):
            with self.subTest(door=argv[1]):
                code, out = self.cli(*argv)
                self.assertEqual(code, 1)
                self.assertIn("acceptance test the orchestrator locked", out)
        self.assertEqual(self.cli("add", "file", self.path("notes.md"), "--behavior", "s1.sets-a", "--why", "docs")[0], 0)

    def test_add_test_gives_a_step_behaviour_its_test_and_step_done_then_commits(self):
        (self.repo / "a.py").write_text("X = 2\n", encoding="utf-8")
        self.cli("verify")
        with self.assertRaises(StepError) as caught:
            step_done(self.port, "s1", "Set A")
        self.assertIn("s1.sets-a has no test", str(caught.exception))
        self.assertIn("has no test test_nope", self.cli("add", "test", self.path("test_a.py") + "#test_nope", "--behavior",
                                              "s1.sets-a", "--what", "AC1: a is 2")[1])
        code, out = self.cli("add", "test", self.path("test_a.py") + "#test_x", "--behavior", "s1.sets-a",
                             "--what", "AC1: a is 2")
        self.assertEqual((code, out), (0, "behaviour s1.sets-a: test test_a.py#test_x added (active)."))
        self.assertIn("plan is delivered", step_done(self.port, "s1", "Set A"))

    def test_drop_file_retire_and_behaviors(self):
        self.assertIn("is changed", self.write_and("a.py", lambda: self.cli("add", "drop-file", self.path("a.py"),
                                                                            "--why", "not needed"))[1])
        self.assertEqual(self.cli("add", "drop-file", self.path("a.py"), "--why", "not needed")[0], 0)
        self.assertNotIn("a.py", [p for op, p in self.port.approved("s1")["grants"] if op == "add"])
        code, out = self.cli("behaviors", "add", "reads", "--what", "w", "--how", "h", "--why", "y", "--test",
                             "test_a.py#test_x")
        self.assertEqual(code, 0, out)
        self.assertIn("reads [active] w - test_a.py#test_x", self.cli("behaviors", "list")[1])
        self.assertEqual(self.cli("behaviors", "check")[0], 0)
        os.remove(self.path("test_a.py"))
        code, out = self.cli("behaviors", "check")
        self.assertEqual(code, 1)
        self.assertIn("reads: test_a.py does not exist", out)
        self.assertEqual(self.cli("add", "retire-test", "reads", "--why", "gone")[0], 0)
        self.assertIn("reads [retired]", self.cli("behaviors", "list")[1])
        self.assertIn("retired", self.cli("add", "retire-test", "reads", "--why", "again")[1])

    def write_and(self, name, then):
        (self.repo / name).write_text("changed\n", encoding="utf-8")
        try:
            return then()
        finally:
            (self.repo / name).write_text("X = 1\n", encoding="utf-8")

    def test_ci_needs_no_session_and_opens_no_ledger(self):
        """s4.ci.door: cli ci prints one line per rule and exits 1 on a failure; it needs a base and a head."""
        from harness.tests import tree
        from harness.utils.orchestra import ci
        home = tree(self, {})  # a home with no state: ci must not make one
        code, out = run_cli(["ci", "--base", "work", "--head", "feature", "--in", str(self.repo)], home)
        self.assertEqual(code, 1)
        lines = out.splitlines()
        self.assertEqual(lines[0], "harness ci: feature into work")
        self.assertEqual([line.split(":")[0] for line in lines[1:-2]], [f"FAIL {rule}" for rule in ci.RULES])
        self.assertTrue(lines[-2].startswith("Result: RED, 9 rule(s) failed"))
        self.assertEqual(lines[-1], "Tests: they run.")  # no child branch: nothing says they wait
        self.assertEqual(list(home.iterdir()), [])
        with unittest.mock.patch.dict(os.environ, {"GITHUB_BASE_REF": "", "GITHUB_HEAD_REF": ""}):
            code, out = run_cli(["ci", "--in", str(self.repo)], home)
        self.assertEqual((code, out), (1, "refused: ci needs --base and --head (in GitHub Actions: GITHUB_BASE_REF and "
                                          "GITHUB_HEAD_REF)"))

    def test_ci_tells_the_workflow_whether_the_branch_has_code(self):
        """s5.ci.code-output: code=no for the start and the registration alone, code=yes once a commit follows."""
        import subprocess
        from harness.tests import tree

        def commit(rel, text, message):
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(text, encoding="utf-8")
            for words in (["add", "-A"], ["commit", "-q", "-m", message]):
                subprocess.run(["git", "-C", str(self.repo), *words], check=True, capture_output=True)
        base = subprocess.run(["git", "-C", str(self.repo), "branch", "--show-current"], check=True,
                              capture_output=True, text=True).stdout.strip()
        subprocess.run(["git", "-C", str(self.repo), "switch", "-q", "-c", "orch/p7/api"], check=True)
        commit(".harness/notes/api/start.md", "# Start of api\n", "#41 api: start")
        commit(".harness/register/api.json", "{}\n", "#41 api: register")
        home, out = tree(self, {}), tree(self, {"out.txt": ""}) / "out.txt"
        for want in ("no", "yes"):
            with unittest.mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(out)}):
                _, text = run_cli(["ci", "--base", base, "--head", "orch/p7/api", "--in", str(self.repo)], home)
            self.assertEqual(out.read_text(encoding="utf-8").splitlines()[-1], f"code={want}")
            self.assertEqual(text.splitlines()[-1], "Tests: they run." if want == "yes" else
                             "Tests: they wait: no commit past the start and the registration yet.")
            if want == "no":
                commit("app/orders.py", "ORDERS = []\n", "#41 api: List orders")
        self.assertEqual(out.read_text(encoding="utf-8"), "code=no\ncode=yes\n")
        self.assertEqual(list(home.iterdir()), [])

    def test_the_entry_runs_from_a_terminal(self):
        code, out, _ = run(entry_of(self.claude_dir, "cli"), args=("--session", "s1", "behaviors", "list"))
        self.assertEqual(code, 0)
        self.assertIn("s1.sets-a", out) if "s1.sets-a" in out else self.assertIn("No behaviour", out)
        self.assertEqual(run(entry_of(self.claude_dir, "cli"), args=("bogus",))[0], 1)


if __name__ == "__main__":
    unittest.main()
