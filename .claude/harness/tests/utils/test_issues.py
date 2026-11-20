"""Sessions part 3, the issues: the parent's harness opens one GitHub issue per child (a fake GitHub here), each with its
card in words and a machine block with its sha256, keeps them in the ticket, and opens none again."""
import csv
import io
import json
import re
import unittest
from unittest import mock

from harness.mcp.actions.orchestra import Spawn, Started, Tickets
from harness.utils.contracts import ActionContext, ActionError, Event
from harness.utils.ledger import store
from harness.utils.orchestra import issues
from harness.utils.plan import tickets as plan_tickets
from harness.tests import tree
from harness.tests.utils.test_review import LOCKED_UNITS, LockedScenario


class FakeIssues:
    """GitHub REST as the issues call it: each POST opens the next issue number."""

    def __init__(self):
        self.calls = []

    def __call__(self, method, path, fields=None):
        self.calls.append((method, path, dict(fields or {})))
        n = 40 + len(self.calls)
        return {"number": n, "html_url": f"https://github.com/o/r/issues/{n}"}


class IssuesTest(LockedScenario):
    def ctx(self, github):
        return ActionContext({"plans": self.port, "session": lambda: "s1", "units": lambda: LOCKED_UNITS,
                              "github": github, "limits": lambda: {"children": 3, "rounds": 3}})

    def tickets(self, github=None):
        return Tickets().run(self.ctx(github or FakeIssues()), {"into": str(self.work)})

    def setUp(self):
        super().setUp()
        self.work = tree(self, {})
        self.port.write(lambda con, rec: plan_tickets.save(con, {**self.port.ticket("s1"), "crew": {}}))  # not started

    def test_the_ticket_file_has_a_row_per_child_and_its_upload_is_recorded(self):
        """s4.ticket.csv and s4.ticket.uploaded: harness code writes the CSV; the hook records Drive's answer."""
        root = "1RootFolderId0001"
        with mock.patch.dict("os.environ", {store.ENV: root}):
            text = self.tickets()
        ticket = self.port.ticket("s1")
        made = ticket[issues.ISSUES]["file"]
        self.assertEqual(made["title"], f"{ticket['draft']}__{ticket['plan']['sha'][:12]}.csv")
        rows = list(csv.reader(io.StringIO((self.work / ".harness-export" / made["title"]).read_text())))
        self.assertEqual(rows[0], list(issues.COLUMNS))
        held = ticket[issues.ISSUES]["children"]["hello"]
        self.assertEqual(rows[1][:9], ["41_issue_hello", ticket["plan"]["sha"], "hello", "github.com/o/r", "#41",
                                       held["sha"], f"orch/p{self.plan}/hello", "orch-probe/hello.py",
                                       "orch-probe/test_hello_ac.py"])
        self.assertRegex(rows[1][9], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIn("First find the store's tickets folder", text)
        self.assertIn(f"  base64Content: sha256:{made['sha256']}:{made['path']}", text.splitlines())
        self.assertIn("  contentMimeType: text/csv", text.splitlines())
        self.assertEqual(store.ticket_held(self.port, made["title"]), "")
        answer = {"id": "1TicketFileId0001", "title": made["title"]}
        notes = store.uploaded(self.port, Event("PostToolUse", "mcp__Google_Drive__create_file",
                                                {"title": made["title"]}, "s1", "/w", answer))
        self.assertEqual(notes, [f"The store holds the ticket file {made['title']} (Drive file 1TicketFileId0001)."])
        self.assertEqual(store.ticket_held(self.port, made["title"]), "1TicketFileId0001")
        other = Event("PostToolUse", "mcp__Google_Drive__create_file", {"title": "x.csv"}, "s1", "/w",
                      {"id": "1OtherFileId00001", "title": "x.csv"})
        self.assertEqual(store.uploaded(self.port, other), [])  # a file the harness did not make is not a ticket

    def test_with_no_store_folder_the_ticket_stays_here(self):
        self.assertIn("no store folder is set", self.tickets())

    def test_each_child_gets_one_issue_kept_in_the_ticket(self):
        """s3.issues.open: one per card, kept; a second call opens none."""
        github = FakeIssues()
        text = self.tickets(github)
        self.assertIn("hello: issue #41 (https://github.com/o/r/issues/41) opened", text)
        (method, path, fields), = github.calls
        self.assertEqual((method, path), ("POST", "repos/o/r/issues"))
        self.assertTrue(fields["title"].startswith(f"[p{self.plan}] hello: Add a hello module"))
        held = self.port.ticket("s1")[issues.ISSUES]["children"]["hello"]
        self.assertEqual((held["number"], held["repo"]), (41, "o/r"))
        self.assertIn("opened before", self.tickets(github))
        self.assertEqual(len(github.calls), 1)

    def test_the_machine_block_and_its_sha(self):
        """s3.issues.block: plan, plan sha, child, repo, branch, start, scope and AC tests; the sha of its JSON."""
        github = FakeIssues()
        self.tickets(github)
        body = github.calls[0][2]["body"]
        found = re.search(re.escape(issues.ISSUE_OPEN) + r"\n(\{.*\})\nsha256: ([0-9a-f]{64})\n" +
                          re.escape(issues.ISSUE_CLOSE), body)
        block = json.loads(found.group(1))
        ticket = self.port.ticket("s1")
        self.assertEqual(block, {"format": "harness-issue/1", "plan": ticket["draft"], "planSha": ticket["plan"]["sha"],
                                 "child": "hello", "repo": "https://github.com/o/r", "path": ".",
                                 "branch": f"orch/p{self.plan}/hello", "start": "",
                                 "scope": ["orch-probe/hello.py"], "tests": [],
                                 "acTests": ["orch-probe/test_hello_ac.py"]})
        self.assertEqual(found.group(2), issues.block_sha(block))
        self.assertEqual(ticket[issues.ISSUES]["children"]["hello"]["sha"], found.group(2))
        self.assertEqual(issues.read_block(body), (block, found.group(2)))

    def test_an_issue_is_in_one_format(self):
        """s1.issue.format: the title, the sections in order, the card in words, the branch and the commit format."""
        github = FakeIssues()
        self.tickets(github)
        title, body = github.calls[0][2]["title"], github.calls[0][2]["body"]
        self.assertEqual(title, f"[p{self.plan}] hello: Add a hello module that greets a person by name")
        self.assertEqual(issues.format_problems(body), [])
        lines = body.split("\n")
        self.assertEqual([h for h in lines if h.startswith("## ")], list(issues.SECTIONS))
        for heading, words in (("## Acceptance criteria", "- AC1: hello('Ann') returns 'Hello, Ann'"),
                               ("## Scope", "- orch-probe/hello.py"), ("## Tests", "- none"),
                               ("## Locked acceptance tests", "- orch-probe/test_hello_ac.py"),
                               ("## Branch", f"orch/p{self.plan}/hello. The child pushes only this branch.")):
            self.assertIn(words, lines[lines.index(heading):], heading)
        self.assertIn("`#<this issue> hello: <what>`", body)
        self.assertIn("`#<this issue> hello: start`, made from the base, which adds the locked acceptance tests", body)
        self.assertIn("the child registers with a comment on this issue", body)
        self.assertEqual(issues.format_problems("## Goal\nx"), ["it has no section Acceptance criteria",
                         "it has no section Scope", "it has no section Tests", "it has no section Locked acceptance "
                         "tests", "it has no section Branch", "it has no section Commits", "it holds no machine block"])

    def test_spawn_waits_for_the_issue_and_the_uploaded_ticket(self):
        """s5.spawn.tickets: a plan with locked tests starts a child only with its issue and, with a store folder,
        the ticket file in the store."""
        ctx = self.ctx(FakeIssues())
        with self.assertRaises(ActionError) as e:
            Spawn().run(ctx, {"name": "hello"})
        self.assertIn("hello has no issue yet: run('orchestra', 'tickets', {})", str(e.exception))
        with mock.patch.dict("os.environ", {store.ENV: "1RootFolderId0001"}):
            self.tickets()
            with self.assertRaises(ActionError) as e:
                Spawn().run(ctx, {"name": "hello"})
            self.assertIn("is not in the store yet", str(e.exception))
            title = self.port.ticket("s1")[issues.ISSUES]["file"]["title"]
            store.uploaded(self.port, Event("PostToolUse", "mcp__Google_Drive__create_file", {"title": title}, "s1",
                                            "/w", {"id": "1TicketFileId0001", "title": title}))
            text = Spawn().run(ctx, {"name": "hello"})
        self.assertIn("issue #41 (https://github.com/o/r/issues/41)", text)
        self.assertIn(title, text)

    def test_no_issue_once_a_child_has_started(self):
        Started().run(self.ctx(FakeIssues()), {"name": "hello", "sid": "session_child0002"})
        with self.assertRaises(ActionError) as e:
            self.tickets()
        self.assertIn("a child has started", str(e.exception))


if __name__ == "__main__":
    unittest.main()
