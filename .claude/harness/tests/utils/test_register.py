"""Sessions part 4, the child's gate: before any work a child checks its brief against its GitHub issue (the machine
block and its sha256) and its row of the ticket file on Drive (the file's sha256), which the hook checks at the
Drive answer and does not keep; take registers only when both agree."""
import base64
import hashlib
import json
import os
import subprocess
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.mcp.actions.orchestra import Take
from harness.utils.contracts import ActionContext, ActionError, Event, Verdict
from harness.utils.orchestra import brief, child, issues, register
from harness.tests import tree
from harness.tests.e2e import copy_tree, git_repo

ALLOW = Verdict("allow")
CARD = {"name": "api", "unit": "home", "goal": "List the orders of a user", "ac": ["GET /orders returns the orders"],
        "change": ["app/orders.py"], "acTests": ["tests/test_orders_ac.py"]}
PLAN = {"id": 7, "sha": "f" * 64, "children": [CARD]}
URL = "https://github.com/o/r"


def records(card=CARD):
    """The issue (its body and entry) and the ticket file (text, entry) the parent's harness writes for a card."""
    block = issues.block_of(PLAN, "pd-x", card, URL, "plan/p7")
    _, body, sha = issues.issue_text(card, block, 7)
    issue = {"repo": "o/r", "number": 41, "url": f"{URL}/issues/41", "sha": sha}
    text = issues.ticket_csv({**PLAN, "children": [card]}, {card["name"]: issue}, "2026-11-18T00:00:00Z")
    made = {"title": "pd-x__ffffffffffff.csv", "sha256": hashlib.sha256(text.encode()).hexdigest()}
    return body, issue, text, made


def github_of(body):
    """A fake GitHub answering the issue with body."""
    return lambda method, path, fields=None: {"number": 41, "body": body}


class RegisterTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(copy_tree(self))
        self.body, self.issue, self.text, self.made = records()
        prompt = brief.brief(7, "pd-x", CARD, "session_p1", rounds=3, start="plan/p7", issue=self.issue,
                             ticket_file=self.made)
        Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": prompt}, "c1", "/w"), {}, ALLOW)
        self.role = self.port.ticket("c1")["child"]

    def drive(self, answer):
        """The hook's Act on a Drive download answer in the child session."""
        return Act(self.port).run(Event("PostToolUse", "mcp__Google_Drive__download_file_content", {"fileId": "1x"},
                                        "c1", "/w", answer), {}, ALLOW)

    def test_the_role_keeps_the_issue_and_the_ticket_file(self):
        self.assertEqual(self.role["record"], {"issue": self.issue, "ticket": self.made})
        self.assertEqual(child.parse(brief.brief(7, "pd-x", CARD, "s", rounds=3))["record"], {})

    def test_the_issue_on_github_agrees_with_the_brief(self):
        """s1.register.issue: block, its own sha256, the brief's sha and the card agree; each disagreement is named."""
        block, problems = register.issue_problems(self.role, github_of(self.body))
        self.assertEqual((problems, block["scope"]), ([], ["app/orders.py"]))
        wider, _, _, _ = records({**CARD, "change": ["app/"]})  # an issue written for another scope
        problems = register.issue_problems(self.role, github_of(wider))[1]
        self.assertIn("the sha256 of issue #41 is not the one the brief names", problems)
        self.assertIn("issue #41 says scope ['app/'], the brief says ['app/orders.py']", problems)
        forged = self.body.replace('"app/orders.py"', '"app/"')  # the block edited, its sha left
        self.assertIn("issue #41 is not in the issue format: its machine block does not match its own sha256",
                      register.issue_problems(self.role, github_of(forged))[1])
        self.assertIn("issue #41 is not in the issue format: it holds no machine block",
                      register.issue_problems(self.role, github_of("no block"))[1])

    def test_an_issue_out_of_format_or_of_other_paths_is_refused(self):
        """s1.register.format: sections in order and a block of harness-issue/1; path and tests as the brief says."""
        moved = self.body.replace("## Commits\n", "").replace("## Goal\n", "## Commits\n## Goal\n")
        problems = register.issue_problems(self.role, github_of(moved))[1]
        self.assertIn("issue #41 is not in the issue format: its section Commits is out of order", problems)
        old = self.body.replace('"format": "harness-issue/1", ', "")
        self.assertIn("issue #41 is not in the issue format: its machine block is of format None, not harness-issue/1",
                      register.issue_problems(self.role, github_of(old))[1])
        tested, _, _, _ = records({**CARD, "tests": ["tests/test_more.py"]})
        problems = register.issue_problems(self.role, github_of(tested))[1]
        self.assertIn("issue #41 says tests ['tests/test_more.py'], the brief says []", problems)
        other = self.body.replace('"path": "."', '"path": "api"')
        self.assertIn("issue #41 says path 'api', the brief says '.'", register.issue_problems(self.role,
                                                                                             github_of(other))[1])

    def test_the_ticket_is_checked_at_the_drive_answer_and_not_kept(self):
        """s1.register.ticket: the content whose sha256 is the brief's is checked at once; only the result stays."""
        self.assertEqual(self.drive({"content": base64.b64encode(b"other,file\n").decode()}), [])
        self.assertIsNone(register.ticket_result(self.port, "c1", self.made["title"]))
        notes = self.drive({"content": base64.b64encode(self.text.encode()).decode(), "mimeType": "text/csv"})
        self.assertIn("its row matches your brief", notes[0])
        result = register.ticket_result(self.port, "c1", self.made["title"])
        self.assertEqual((result["problems"], result["planSha"], result["sha256"]), ([], "f" * 64, self.made["sha256"]))
        kept = json.dumps([dict(r) for r in self.port.rows("SELECT * FROM pl_notes WHERE kind = 'child.ticket'")])
        self.assertNotIn("approved at", kept)  # the file itself is never kept
        self.assertNotIn("41_issue_api", kept)
        self.assertEqual(len(self.drive(self.text)), 1)  # a plain text answer is read too

    def test_a_row_that_differs_from_the_brief_is_refused_with_the_field(self):
        _, _, other, _ = records({**CARD, "acTests": ["tests/other_ac.py"]})
        plan_sha, problems = register.row_problems(self.role, other)
        self.assertEqual(plan_sha, "f" * 64)
        self.assertIn("the ticket row says AC tests 'tests/other_ac.py', the brief says 'tests/test_orders_ac.py'",
                      problems)
        self.assertEqual(register.row_problems(self.role, "a,b\n1,2\n")[1],
                         ["the ticket file does not have the harness's columns"])


def git(repo, *args):
    """git in repo; its output."""
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


class TakeTest(unittest.TestCase):
    """take with a real origin: the plan branch holds the locked test; GitHub is a fake that answers the issue."""

    def setUp(self):
        self.port = LedgerPort(copy_tree(self))
        self.origin = tree(self, {})
        git(self.origin, "init", "-q", "--bare")
        self.repo = git_repo(self, {"a.py": "X = 1\n"})
        git(self.repo, "remote", "add", "origin", str(self.origin))
        git(self.repo, "push", "-q", "origin", "work")
        git(self.repo, "switch", "-q", "-c", "plan/p7")
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_orders_ac.py").write_text("# locked\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "locked")
        git(self.repo, "push", "-q", "origin", "plan/p7")
        git(self.repo, "switch", "-q", "work")
        git(self.repo, "branch", "-q", "-D", "plan/p7")
        self.body, self.issue, self.text, self.made = records()
        prompt = brief.brief(7, "pd-x", CARD, "session_p1", rounds=3, start="plan/p7", issue=self.issue,
                             ticket_file=self.made)
        Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": prompt}, "c1", str(self.repo)), {}, ALLOW)
        here = os.getcwd()
        os.chdir(self.repo)  # the MCP server runs in the project's folder
        self.addCleanup(os.chdir, here)

    def take(self, body=None):
        ctx = ActionContext({"plans": self.port, "session": lambda: "c1", "github": github_of(body or self.body),
                             "commit_judge": lambda *a: ALLOW, "git_judge": lambda *a: ALLOW})
        return Take().run(ctx, {})

    def ticket(self):
        Act(self.port).run(Event("PostToolUse", "mcp__Google_Drive__download_file_content", {"fileId": "1x"}, "c1",
                                 "/w", {"content": base64.b64encode(self.text.encode()).decode()}), {}, ALLOW)

    def test_take_registers_and_then_opens_the_card_plan(self):
        """s2.take.registers: no ticket checked yet, take says how; both checks green, the card plan opens."""
        with self.assertRaises(ActionError) as e:
            self.take()
        self.assertIn(f"search_files with the query: title = '{self.made['title']}'", str(e.exception))
        self.assertIsNone(self.port.approved("c1"))
        self.ticket()
        text = self.take()
        self.assertTrue(text.startswith(f"Registered: issue #41 and your row of {self.made['title']} match your brief"))
        self.assertIn("Card plan", text)
        self.assertEqual(git(self.repo, "branch", "--show-current").strip(), "orch/p7/api")
        self.assertTrue((self.repo / "tests" / "test_orders_ac.py").is_file())
        self.assertEqual(len(self.port.rows("SELECT 1 AS x FROM pl_notes WHERE kind = 'child.registered'")), 1)

    def test_the_approval_names_the_registration_and_take_pushes_it(self):
        """s3.register.approval: the ledger's grant of the card plan names issue #41 and the record's commit, which
        is the first commit of the branch on origin, over the plan branch."""
        self.ticket()
        text = self.take()
        sha = git(self.origin, "rev-parse", "orch/p7/api").strip()
        self.assertIn("Pushed orch/p7/api", text)
        self.assertEqual(git(self.origin, "log", "--format=%s", "plan/p7..orch/p7/api").splitlines(),
                         [git(self.origin, "log", "-1", "--format=%s", sha).strip()])
        self.assertTrue(git(self.origin, "log", "-1", "--format=%s", sha).startswith("#41 api: register (issue "))
        grants = [json.loads(r["body"]) for r in self.port.rows("SELECT body FROM pl_logs")]
        grant = [g for g in grants if g.get("what") == "grant"][-1]
        self.assertTrue(grant["by"].endswith(f", registration #41 in {sha[:12]}"), grant["by"])
        self.assertEqual(self.port.approved("c1")["base"], sha)

    def test_a_mismatch_pushes_its_reason_and_opens_no_plan(self):
        """s2.take.refused: the issue on GitHub is for another scope; the reason is question 1 on the branch."""
        self.ticket()
        wider, _, _, _ = records({**CARD, "change": ["app/"]})
        with self.assertRaises(ActionError) as e:
            self.take(wider)
        self.assertIn("Registration failed, so you may not work on this card", str(e.exception))
        self.assertIn("Stop now", str(e.exception))
        self.assertIsNone(self.port.approved("c1"))
        note = git(self.origin, "show", "orch/p7/api:.harness/notes/api/question-1.md")
        self.assertIn("issue #41 says scope ['app/'], the brief says ['app/orders.py']", note)
        self.assertEqual(git(self.origin, "show", "--name-only", "--format=", "orch/p7/api").split(),
                         [".harness/notes/api/question-1.md"])  # the tip is the question: the parent's check reads it


if __name__ == "__main__":
    unittest.main()
