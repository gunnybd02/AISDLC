"""Sessions part 5, the doorbell (utils/orchestra/doorbell.py): when a CI result wakes the parent, the harness reads
each child's draft on GitHub (a fake here): the project's own CI on the head commit (every check run and status,
whatever they are named; none at all is no CI) and the comments (the child's question or handback names its commit);
it records what is new once and names the next step."""
import json
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.utils.git.github import GitHubError
from harness.utils.orchestra import doorbell
from harness.utils.orchestra.draft import DRAFTS
from harness.utils.orchestra.talk import MARK
from harness.utils.plan import tickets
from harness.tests.e2e import copy_tree

HEAD = "a" * 40
QUESTION = ("**Question of api** (plan 7)\n\nWhich status code for a closed account?\n\n"
            + MARK.format(meta=json.dumps({"child": "api", "kind": "question", "plan": 7, "n": 1, "sha": HEAD},
                                          sort_keys=True)))
HANDBACK = ("**Handback of api** (plan 7)\n\nChanged: app/orders.py\n\n```json\n{\"name\": \"api\"}\n```\n\n"
            + MARK.format(meta=json.dumps({"child": "api", "kind": "handback", "plan": 7, "sha": HEAD}, sort_keys=True)))


def said(body, n=1):
    """A comment of the child on its draft, as GitHub gives it."""
    return {"id": n, "body": body, "html_url": f"https://github.com/o/r/pull/5#c{n}", "user": {"login": "bot"}}


def run(name="lint", status="completed", conclusion="success"):
    """One check run of the project's own CI."""
    return {"name": name, "status": status, "conclusion": conclusion, "html_url": f"https://github.com/o/r/runs/{name}"}


def status(context="secrets", state="success"):
    """One commit status of the project's own CI."""
    return {"context": context, "state": state, "target_url": f"https://ci.example/{context}"}


class FakeGitHub:
    """GitHub REST for one draft, #5 of o/r, in the state a test sets: its head, its check runs, its statuses and its
    comments; refuse makes the CI unreadable."""

    def __init__(self, runs=(), statuses=(), comments=(), refuse=False):
        self.runs, self.statuses, self.comments, self.refuse = list(runs), list(statuses), list(comments), refuse

    def __call__(self, method, path, fields=None):
        if path == "repos/o/r/pulls/5":
            return {"head": {"sha": HEAD}}
        if path == f"repos/o/r/commits/{HEAD}/check-runs?filter=latest&per_page=100":
            if self.refuse:
                raise GitHubError("gh api: HTTP 502")
            return {"check_runs": self.runs, "total_count": len(self.runs)}
        if path == f"repos/o/r/commits/{HEAD}/status":
            return {"statuses": self.statuses, "total_count": len(self.statuses)}
        if path == "repos/o/r/issues/5/comments?per_page=100":
            return self.comments
        raise AssertionError(path)


GREEN = [run("lint"), run("nets", conclusion="neutral"), run("docs", conclusion="skipped")]
RED = [run("lint"), run("secrets", conclusion="failure")]


class CiStateTest(unittest.TestCase):
    def test_every_check_run_and_status_makes_one_state(self):
        """s1.doorbell.ci-state: red, running, none, green and unknown, whatever the checks are named."""
        for github, want in (
                (FakeGitHub(GREEN, [status()]), ("green", [])),
                (FakeGitHub(RED), ("red", ["secrets (https://github.com/o/r/runs/secrets)"])),
                (FakeGitHub([run("lint", conclusion="timed_out")]), ("red", ["lint (https://github.com/o/r/runs/lint)"])),
                (FakeGitHub(GREEN, [status(state="error")]), ("red", ["secrets (https://ci.example/secrets)"])),
                (FakeGitHub([run("lint", status="in_progress", conclusion=None)]), ("running", [])),
                (FakeGitHub(GREEN, [status(state="pending")]), ("running", [])),
                (FakeGitHub(), ("none", [])),
                (FakeGitHub(statuses=[status()]), ("green", []))):
            with self.subTest(want=want[0], runs=len(github.runs), statuses=len(github.statuses)):
                self.assertEqual(doorbell.ci_state(github, "o/r", HEAD), want)
        state, why = doorbell.ci_state(FakeGitHub(refuse=True), "o/r", HEAD)
        self.assertEqual(state, "unknown")
        self.assertIn("HTTP 502", why[0])


class DoorbellTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(copy_tree(self))
        self.port.write(lambda con, rec: tickets.save(con, {**tickets.blank("s1"), DRAFTS: {
            "api": {"repo": "o/r", "number": 5, "url": "https://github.com/o/r/pull/5", "watched": 1}},
            "crew": {"api": {"sid": "session_child0001", "state": "running"}}}))

    def ring(self, github):
        return doorbell.ring(self.port, "s1", github)

    def test_each_state_names_its_next_step(self):
        """s1.doorbell.ci-state: wait, reject naming the failed checks, answer, or check then accept; no CI skips the
        CI phase."""
        receipt, question = [said(HANDBACK)], [said(QUESTION)]
        older = [said(HANDBACK.replace(HEAD, "b" * 40))]  # a handback of an older commit is not for the head
        short = HEAD[:12]
        for github, words in (
                (FakeGitHub([run(status="queued", conclusion=None)]), f"CI runs on {short}: wait."),
                (FakeGitHub(RED, comments=receipt),
                 f"CI is RED on {short}: secrets (https://github.com/o/r/runs/secrets). Send it back: "
                 "run('orchestra', 'reject', {name: 'api', why: '<these failures>'})."),
                (FakeGitHub(RED), f"CI is red on {short} while it works (no handback yet): wait."),
                (FakeGitHub(GREEN, comments=question), "it asked a question (its comment below)"),
                (FakeGitHub(GREEN, comments=receipt),
                 f"it handed back and CI is green on {short}: run('orchestra', 'check', {{name: 'api'}}), then accept."),
                (FakeGitHub(comments=receipt),
                 f"it handed back and no CI on {short}: run('orchestra', 'check', {{name: 'api'}}), then accept."),
                (FakeGitHub(GREEN, comments=older), f"CI is green on {short}, no handback yet: wait."),
                (FakeGitHub(refuse=True, comments=receipt), f"the CI of {short} cannot be read")):
            with self.subTest(words=words[:30]):
                self.assertIn(f"api (draft #5): {words}", self.ring(github))

    def test_results_and_comments_are_recorded_once_with_sender_and_receiver(self):
        """s2.doorbell.read: each CI result and each comment is one ledger row; a second ring adds none."""
        comments = [{"id": 11, "body": QUESTION, "html_url": "https://github.com/o/r/pull/5#c11",
                     "user": {"login": "bot"}},
                    {"id": 12, "body": "Looks fine to me", "html_url": "https://github.com/o/r/pull/5#c12",
                     "user": {"login": "someone"}}]
        github = FakeGitHub(GREEN, comments=comments)
        text = self.ring(github)
        self.assertIn("  New comment: from api: **Question of api** (plan 7) Which status code for a closed account?", text)
        self.assertIn("  New comment: from @someone: Looks fine to me", text)
        self.assertNotIn("New comment", self.ring(github))  # nothing new the second time
        results = self.port.rows("SELECT target, key, text FROM pl_notes WHERE kind = 'ci.result'")
        self.assertEqual([(r["target"], r["key"]) for r in results], [("o/r#5", f"{HEAD}:green")])
        said = {json.loads(r["text"])["from"]: json.loads(r["text"]) for r in
                self.port.rows("SELECT text FROM pl_notes WHERE kind = 'child.comment'")}
        self.assertEqual((said["api"]["fromSession"], said["api"]["to"]), ("session_child0001", "s1"))
        self.assertEqual((said["@someone"]["fromSession"], said["@someone"]["to"]), (None, "s1"))
        self.ring(FakeGitHub([run(status="in_progress", conclusion=None)]))  # a new state of the same commit is a new row
        self.assertEqual(len(self.port.rows("SELECT 1 AS x FROM pl_notes WHERE kind = 'ci.result'")), 2)

    def test_a_comment_of_the_orchestrator_is_never_the_childs(self):
        """s1.talk.from-parent: the parent's own answer is recorded from the orchestrator to the child."""
        answer = ("**Answer of the orchestrator** (plan 7)\n\nUse 409.\n\n" + MARK.format(meta=json.dumps(
            {"child": "api", "from": "orchestrator", "kind": "answer", "plan": 7}, sort_keys=True)))
        text = self.ring(FakeGitHub(GREEN, comments=[
            {"id": 21, "body": answer, "html_url": "https://github.com/o/r/pull/5#c21", "user": {"login": "bot"}}]))
        self.assertIn("  New comment: from orchestrator: **Answer of the orchestrator** (plan 7) Use 409.", text)
        kept = json.loads(self.port.rows("SELECT text FROM pl_notes WHERE kind = 'child.comment'")[0]["text"])
        self.assertEqual((kept["from"], kept["fromSession"], kept["to"]), ("orchestrator", "s1", "session_child0001"))

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

    def test_a_github_notification_read_names_the_doorbell(self):
        """s4.doorbell.rung-notifications: in the cloud the CI result is a notification; its answer gets the line,
        as text or nested in an object."""
        from harness.assemble.engine.runner import Act
        from harness.utils.contracts import Event, Verdict
        line = "A GitHub event woke you: run('orchestra', 'doorbell', {})."
        wake = ('<wake reason="external-event"><event source="github" kind="check_run.completed" pr="5">harness-ci '
                'completed: success</event></wake>\n0 remaining')
        for answer in (wake, {"notifications": [{"body": wake}], "remaining": 0}):
            notes = Act(self.port).run(Event("PostToolUse", doorbell.NOTIFICATIONS, {}, "s1", "/w", answer), {},
                                       Verdict("allow"))
            self.assertTrue(any(n.startswith(line) for n in notes))

    def test_another_tool_or_a_notification_without_github_gets_no_line(self):
        """s4.doorbell.rung-quiet: the line shows only when a GitHub event was read."""
        from harness.utils.contracts import Event
        wake = '<event source="github" kind="check_run.completed">harness-ci completed</event>'
        self.assertEqual(doorbell.rung(self.port, Event("PostToolUse", "Bash", {}, "s1", "/w", wake)), [])
        self.assertEqual(doorbell.rung(self.port, Event("PostToolUse", doorbell.NOTIFICATIONS, {}, "s1", "/w",
                                                        "A scheduled check-in: look at the plan. 0 remaining")), [])
        self.assertEqual(doorbell.rung(self.port, Event("PostToolUse", doorbell.NOTIFICATIONS, {}, "s9", "/w",
                                                        wake)), [])  # no draft in that session
        self.assertEqual(doorbell.rung(self.port, Event("PreToolUse", doorbell.NOTIFICATIONS, {}, "s1", "/w")), [])
        self.assertEqual(doorbell.words({"a": ["x", {"b": "y"}], "n": 3}), ["x", "y"])

    def test_no_draft_and_an_ended_child(self):
        self.port.write(lambda con, rec: tickets.save(con, {**tickets.latest(con, "s1"),
                                                             "crew": {"api": {"sid": "x", "state": "accepted"}}}))
        self.assertEqual(self.ring(FakeGitHub()), "api: accepted; nothing to do.")
        self.assertIn("No child has a draft pull request", doorbell.ring(self.port, "s9", FakeGitHub()))


if __name__ == "__main__":
    unittest.main()
