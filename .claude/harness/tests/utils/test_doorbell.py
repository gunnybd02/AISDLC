"""Sessions part 5, the doorbell (utils/orchestra/doorbell.py): when a CI result wakes the parent, the harness reads
each child's draft on GitHub (a fake here): the harness-ci check run of the head commit, the FAIL lines of a red job's
log, the new comments and the files of the head commit; it records what is new once and names the next step."""
import json
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.utils.orchestra import doorbell
from harness.utils.orchestra.draft import DRAFTS, MARK
from harness.utils.plan import tickets
from harness.tests.e2e import copy_tree

HEAD = "a" * 40
LOG = ("2026-11-19T01:02:03.1234567Z harness ci: orch/p7/api into plan/p7\n"
       "2026-11-19T01:02:03.2234567Z PASS branch: orch/p7/api is the branch of issue #41\n"
       "2026-11-19T01:02:03.3234567Z FAIL scope: outside the scope of the issue: app/other.py\n"
       "2026-11-19T01:02:03.4234567Z Result: RED, 1 rule(s) failed: scope.\n")
QUESTION = ("**Question of api** (plan 7)\n\nWhich status code for a closed account?\n\n"
            + MARK.format(meta=json.dumps({"child": "api", "kind": "question", "plan": 7}, sort_keys=True)))


class FakeGitHub:
    """GitHub REST for one draft, #5 of o/r, in the state a test sets."""

    def __init__(self, run=None, files=(), comments=()):
        self.run, self.files, self.comments = run, list(files), list(comments)

    def __call__(self, method, path, fields=None):
        if path == "repos/o/r/pulls/5":
            return {"head": {"sha": HEAD}}
        if path == f"repos/o/r/commits/{HEAD}/check-runs":
            return {"check_runs": [{"name": "other"}] + ([self.run] if self.run else [])}
        if path == f"repos/o/r/commits/{HEAD}":
            return {"files": [{"filename": f} for f in self.files]}
        if path == "repos/o/r/issues/5/comments":
            return self.comments
        raise AssertionError(path)


def run(status="completed", conclusion="success"):
    return {"name": "harness-ci", "id": 77, "status": status, "conclusion": conclusion,
            "html_url": "https://github.com/o/r/runs/77"}


class DoorbellTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(copy_tree(self))
        self.port.write(lambda con, rec: tickets.save(con, {**tickets.blank("s1"), DRAFTS: {
            "api": {"repo": "o/r", "number": 5, "url": "https://github.com/o/r/pull/5", "watched": 1}},
            "crew": {"api": {"sid": "session_child0001", "state": "running"}}}))
        self.logs = []

    def log(self, method, path):
        self.logs.append(path)
        return LOG

    def ring(self, github):
        return doorbell.ring(self.port, "s1", github, self.log)

    def test_each_state_names_its_next_step(self):
        """s2.doorbell.read: wait, reject with the failed rules, answer, or check then accept."""
        receipt, question = ".harness/handback/api.json", ".harness/notes/api/question-1.md"
        short = HEAD[:12]
        for github, words in (
                (FakeGitHub(), f"no harness-ci result on {short} yet: wait."),
                (FakeGitHub(run("in_progress", None)), f"CI runs on {short}: wait."),
                (FakeGitHub(run(conclusion="failure"), ["app/other.py"]),
                 f"CI is RED on {short}: FAIL scope: outside the scope of the issue: app/other.py. Send it back: "
                 "run('orchestra', 'reject', {name: 'api', why: '<these failures>'})."),
                (FakeGitHub(run(conclusion="success"), [question]), "it asked a question (its comment below)"),
                (FakeGitHub(run(conclusion="success"), [receipt]),
                 f"it handed back and CI is green on {short}: run('orchestra', 'check', {{name: 'api'}}), then accept."),
                (FakeGitHub(run(conclusion="success"), ["app/orders.py"]), f"CI is green on {short}, no receipt yet: wait.")):
            with self.subTest(words=words[:30]):
                self.assertIn(f"api (draft #5): {words}", self.ring(github))
        self.assertEqual(self.logs, ["repos/o/r/actions/jobs/77/logs"])  # only a red job's log is read

    def test_red_tests_wait_while_the_child_works_and_send_it_back_after_its_handback(self):
        self.log = lambda method, path: "2026-11-19T01:02:03Z FAILED (failures=1)\n"  # tests, no rule line
        failed = run(conclusion="failure")
        self.assertIn("its tests are red on", self.ring(FakeGitHub(failed, ["app/orders.py"])))
        self.assertIn("CI is RED on", self.ring(FakeGitHub(failed, [".harness/handback/api.json"])))
        self.assertIn("see https://github.com/o/r/runs/77", self.ring(FakeGitHub(failed, [".harness/handback/api.json"])))

    def test_results_and_comments_are_recorded_once_with_sender_and_receiver(self):
        """s2.doorbell.read: each CI result and each comment is one ledger row; a second ring adds none."""
        comments = [{"id": 11, "body": QUESTION, "html_url": "https://github.com/o/r/pull/5#c11",
                     "user": {"login": "bot"}},
                    {"id": 12, "body": "Looks fine to me", "html_url": "https://github.com/o/r/pull/5#c12",
                     "user": {"login": "someone"}}]
        github = FakeGitHub(run(conclusion="success"), [".harness/notes/api/question-1.md"], comments)
        text = self.ring(github)
        self.assertIn("  New comment: from api: **Question of api** (plan 7) Which status code for a closed account?", text)
        self.assertIn("  New comment: from @someone: Looks fine to me", text)
        self.assertNotIn("New comment", self.ring(github))  # nothing new the second time
        results = self.port.rows("SELECT target, key, text FROM pl_notes WHERE kind = 'ci.result'")
        self.assertEqual([(r["target"], r["key"]) for r in results], [("o/r#5", f"{HEAD}:success")])
        said = {json.loads(r["text"])["from"]: json.loads(r["text"]) for r in
                self.port.rows("SELECT text FROM pl_notes WHERE kind = 'child.comment'")}
        self.assertEqual((said["api"]["fromSession"], said["api"]["to"]), ("session_child0001", "s1"))
        self.assertEqual((said["@someone"]["fromSession"], said["@someone"]["to"]), (None, "s1"))
        self.ring(FakeGitHub(run("in_progress", None)))  # a new state of the same commit is a new row
        self.assertEqual(len(self.port.rows("SELECT 1 AS x FROM pl_notes WHERE kind = 'ci.result'")), 2)

    def test_a_github_wake_up_of_a_parent_with_drafts_names_the_doorbell(self):
        """s3.doorbell.rung: the hook adds the line at a GitHub event; another prompt, or a session with no draft,
        gets none."""
        from harness.assemble.engine.runner import Act
        from harness.utils.contracts import Event, Verdict

        def prompt(text, sid="s1"):
            return Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": text}, sid, "/w"), {}, Verdict("allow"))
        wake = ('<wake reason="external-event"><event source="github" kind="check_run" pr="5">harness-ci completed: '
                'failure</event></wake>')
        line = "A GitHub event woke you: run('orchestra', 'doorbell', {})."
        self.assertTrue(any(n.startswith(line) for n in prompt(wake)))
        self.assertFalse(any(n.startswith(line) for n in prompt("go on with the plan")))
        self.assertFalse(any(n.startswith(line) for n in prompt(wake, sid="s9")))  # no draft in that session

    def test_no_draft_and_an_ended_child(self):
        self.port.write(lambda con, rec: tickets.save(con, {**tickets.latest(con, "s1"),
                                                             "crew": {"api": {"sid": "x", "state": "accepted"}}}))
        self.assertEqual(self.ring(FakeGitHub()), "api: accepted; nothing to do.")
        self.assertIn("No child has a draft pull request", doorbell.ring(self.port, "s9", FakeGitHub(), self.log))


if __name__ == "__main__":
    unittest.main()
