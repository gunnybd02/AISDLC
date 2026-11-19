"""Sessions part 5, the CI workflow (utils/orchestra/workflow.py): the GitHub Actions file lock pushes on a plan
branch. It is parsed here as GitHub reads it (PyYAML; skipped where it is missing)."""
import unittest

from harness.utils.orchestra import workflow

SOURCE = {"url": "https://github.com/gunnybd02/AISDLC", "sha": "1a72c5c17b459e9527827cf5afc173f90a887da8"}
API = ({"name": "api", "tests": ["tests/test_orders.py"]},
       {"repo": "https://github.com/o/r", "path": "services/api", "verify": ["{python}", "-m", "unittest"]})
WEB = ({"name": "web", "acTests": ["tests/test_a_ac.py", "tests/test b_ac.py"]},
       {"repo": "https://github.com/o/r", "path": ".", "verify": ["{python}", "{test}"]})
DOCS = ({"name": "docs"}, {"repo": "https://github.com/o/r", "path": "docs", "verify": []})


class WorkflowTest(unittest.TestCase):
    def parsed(self, children=(API, WEB, DOCS)):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is not installed")
        return yaml.safe_load(workflow.text(7, list(children), SOURCE))

    def test_the_workflow_runs_the_pinned_rules_then_the_tests_of_each_child(self):
        """s1.workflow.text: trigger, read-only rights, the pinned harness, harness ci, a test step per child."""
        doc = self.parsed()
        self.assertEqual(doc["on"], {"pull_request": {"branches": ["plan/p7"]}})
        self.assertEqual(doc["permissions"], {"contents": "read", "issues": "read", "pull-requests": "read"})
        job = doc["jobs"]["harness-ci"]
        self.assertEqual((job["if"], job["runs-on"]), ("startsWith(github.head_ref, 'orch/p7/')", "ubuntu-latest"))
        checkout, python, harness, ci, *tests = job["steps"]
        self.assertEqual(checkout, {"uses": "actions/checkout@v4", "with": {"fetch-depth": 0}})
        self.assertEqual(python, {"uses": "actions/setup-python@v5", "with": {"python-version": "3.13"}})
        self.assertEqual(harness["run"].splitlines(), [
            'git clone --quiet https://github.com/gunnybd02/AISDLC "$RUNNER_TEMP/harness"',
            'git -C "$RUNNER_TEMP/harness" checkout --quiet 1a72c5c17b459e9527827cf5afc173f90a887da8'])
        self.assertEqual((ci["id"], ci["env"]), ("ci", {"GH_TOKEN": "${{ github.token }}"}))
        self.assertEqual(ci["run"].strip(), 'python "$RUNNER_TEMP/harness/.claude/harness/entry/cli.py" ci --base '
                                            '"$GITHUB_BASE_REF" --head "$GITHUB_HEAD_REF" '
                                            '--sha "${{ github.event.pull_request.head.sha }}"')
        self.assertEqual([(t["name"], t.get("working-directory"), t["run"].strip()) for t in tests], [
            ("tests of api", "services/api", "python -m unittest"),
            ("tests of web (1)", None, "python tests/test_a_ac.py"),
            ("tests of web (2)", None, "python 'tests/test b_ac.py'")])  # docs names no command: no step
        self.assertEqual(tests[0]["if"], "${{ !cancelled() && github.head_ref == 'orch/p7/api' && "
                                         "steps.ci.outputs.code == 'yes' }}")

    def test_each_test_step_waits_until_harness_ci_says_the_branch_has_code(self):
        """s5.workflow.tests-wait: the ci step has the id ci; every test step runs only when its code output is yes."""
        lines = workflow.text(7, [API, WEB, DOCS], SOURCE).splitlines()
        self.assertEqual(lines[lines.index("      - name: harness ci") + 1], "        id: ci")
        steps = [n for n, line in enumerate(lines) if line.startswith("      - name: tests of ")]
        self.assertEqual(len(steps), 3)
        for n in steps:
            self.assertTrue(lines[n + 1].endswith("&& steps.ci.outputs.code == 'yes' }}"), lines[n + 1])

    def test_harness_ci_is_given_the_commit_under_test(self):
        """s2.workflow.head-sha: the job passes the pull request's head sha (live run 5: the tip raced the test)."""
        text = workflow.text(7, [API], SOURCE)
        self.assertIn('--sha "${{ github.event.pull_request.head.sha }}"', text)

    def test_only_a_public_url_and_a_full_commit_are_pinned(self):
        for source in ({"url": "https://user:" + "x@github.com/o/h", "sha": SOURCE["sha"]},  # credentials in it
                       {"url": "git@github.com:o/h.git", "sha": SOURCE["sha"]},
                       {"url": SOURCE["url"], "sha": "1a72c5c"}, {}):
            with self.subTest(source=source), self.assertRaises(workflow.WorkflowError):
                workflow.text(7, [API], source)
        self.assertEqual(workflow.WORKFLOW, ".github/workflows/harness-ci.yml")


if __name__ == "__main__":
    unittest.main()
