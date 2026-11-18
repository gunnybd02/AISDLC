"""Sessions part 4, the child's gate: before any work a child checks its brief against its GitHub issue (the machine
block and its sha256) and its row of the ticket file on Drive (the file's sha256), which the hook checks at the
Drive answer and does not keep; take registers only when both agree."""
import base64
import hashlib
import json
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.utils.contracts import Event, Verdict
from harness.utils.orchestra import brief, child, issues, register
from harness.tests.e2e import copy_tree

ALLOW = Verdict("allow")
CARD = {"name": "api", "unit": "home", "goal": "List the orders of a user", "ac": ["GET /orders returns the orders"],
        "change": ["app/orders.py"], "acTests": ["tests/test_orders_ac.py"]}
PLAN = {"id": 7, "sha": "f" * 64, "children": [CARD]}
URL = "https://github.com/o/r"


def records(card=CARD):
    """The issue (its body and entry) and the ticket file (text, entry) the parent's harness writes for a card."""
    block = issues.block_of(PLAN, "pd-x", card, URL, "plan/p7")
    _, body, sha = issues.issue_text(card, block)
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
        self.assertIn("the machine block of issue #41 does not match its own sha256",
                      register.issue_problems(self.role, github_of(forged))[1])
        self.assertEqual(register.issue_problems(self.role, github_of("no block"))[1], ["issue #41 holds no machine block"])

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


if __name__ == "__main__":
    unittest.main()
