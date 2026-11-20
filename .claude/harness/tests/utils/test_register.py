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
from harness.utils.orchestra import brief, child, issues, register, talk
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

    def test_a_ticket_drive_saved_to_a_file_is_checked_and_the_file_deleted(self):
        """s1.register.saved: the answer shape of the live run of 2026-11-19: no content, a saved file named; only a
        file of a tool-results folder under SAVED_ROOT is read, and the ticket's is deleted after the check."""
        from unittest import mock
        root = tree(self, {})
        results = root / "-home-user-AISDLC" / "15f7421a" / "tool-results"
        results.mkdir(parents=True)
        saved, other = results / "mcp-caaed075-blob-1.csv", results / "mcp-caaed075-blob-2.csv"
        saved.write_text(self.text, encoding="utf-8")
        other.write_text("a,b\n1,2\n", encoding="utf-8")
        outside = root / "elsewhere.csv"
        outside.write_text(self.text, encoding="utf-8")

        def answer(path):
            return [{"type": "text", "text": f"[Resource from caaed075 at googledrive://file/1x] Binary content "
                                             f"(text/csv, {len(self.text)} bytes) saved to {path}"},
                    {"type": "text", "text": json.dumps({"id": "1x", "title": self.made["title"], "mimeType": "text/csv",
                                                         "content": "(file sent separately)"})}]
        with mock.patch.object(register, "SAVED_ROOT", root):
            self.assertEqual(self.drive(answer(outside)), [])  # not in a tool-results folder: never read
            self.assertEqual(self.drive(answer(other)), [])  # another file: not the ticket, left alone
            self.assertEqual(self.drive(answer(root / "gone" / "tool-results" / "x.csv")), [])  # no such file
            notes = self.drive(answer(saved))
        self.assertTrue(outside.exists() and other.exists())
        self.assertIn("(the file Drive's answer was saved to, now deleted): its row matches your brief", notes[0])
        self.assertFalse(saved.exists())
        result = register.ticket_result(self.port, "c1", self.made["title"])
        self.assertEqual((result["problems"], result["sha256"]), ([], self.made["sha256"]))

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


class FakeGitHub:
    """GitHub REST for issue #41 (its body) and the comments of #41 and of the draft #5, kept as they are posted."""

    def __init__(self, body):
        self.body, self.comments, self.posts = body, {}, []

    def __call__(self, method, path, fields=None):
        if path == "repos/o/r/issues/41":
            return {"number": 41, "body": self.body}
        number = path.split("/issues/")[1].split("/")[0]
        if method == "GET":
            return list(self.comments.get(number, []))
        made = {"id": 800 + len(self.posts), "html_url": f"{URL}/issues/{number}#c{len(self.posts)}",
                "body": fields["body"]}
        self.posts.append(number)
        self.comments.setdefault(number, []).append(made)
        return made


class TakeTest(unittest.TestCase):
    """take with a real origin: the plan branch holds the locked test; GitHub is a fake that answers the issue and
    keeps the comments."""

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
        self.github = FakeGitHub(self.body)
        prompt = brief.brief(7, "pd-x", CARD, "session_p1", rounds=3, start="plan/p7", issue=self.issue,
                             ticket_file=self.made, pr={"repo": "o/r", "number": 5, "url": f"{URL}/pull/5"})
        Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": prompt}, "c1", str(self.repo)), {}, ALLOW)
        here = os.getcwd()
        os.chdir(self.repo)  # the MCP server runs in the project's folder
        self.addCleanup(os.chdir, here)

    def take(self, body=None):
        self.github.body = body or self.body
        return Take().run(ActionContext({"plans": self.port, "session": lambda: "c1", "github": self.github}), {})

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

    def test_take_posts_the_registration_on_the_issue_and_commits_nothing(self):
        """s2.register.on-issue: the registration is one comment on issue #41, named by the card plan's approval; the
        branch gets no commit and no file, nothing is pushed, and a second take posts none."""
        self.ticket()
        self.take()
        self.assertEqual(self.github.posts, ["41"])
        meta = talk.read(self.github.comments["41"][0])
        self.assertEqual((meta["kind"], meta["child"], meta["branch"], meta["issueSha"], meta["planSha"]),
                         ("register", "api", "orch/p7/api", self.issue["sha"], "f" * 64))
        self.assertEqual(register.registration_of(self.github.comments["41"], "api")["id"], 800)
        planned = git(self.origin, "rev-parse", "plan/p7").strip()
        self.assertEqual(git(self.repo, "rev-parse", "HEAD").strip(), planned)  # no commit on the branch
        self.assertEqual(git(self.origin, "branch", "--list", "orch/p7/api"), "")  # nothing pushed
        grants = [json.loads(r["body"]) for r in self.port.rows("SELECT body FROM pl_logs")]
        grant = [g for g in grants if g.get("what") == "grant"][-1]
        self.assertTrue(grant["by"].endswith(", registration #41 in comment 800"), grant["by"])
        self.assertEqual(self.port.approved("c1")["base"], planned)
        self.assertIn("is open already", self.take())
        self.assertEqual(self.github.posts, ["41"])

    def test_a_mismatch_pushes_an_empty_stop_and_a_question_comment(self):
        """s2.register.on-issue: the issue on GitHub is for another scope; the reason is question 1, a comment on the
        draft #5 naming the empty commit pushed on the branch, which wakes the parent through CI."""
        self.ticket()
        wider, _, _, _ = records({**CARD, "change": ["app/"]})
        with self.assertRaises(ActionError) as e:
            self.take(wider)
        self.assertIn("Registration failed, so you may not work on this card", str(e.exception))
        self.assertIn("Stop now", str(e.exception))
        self.assertIn("a comment on your draft pull request #5", str(e.exception))
        self.assertIsNone(self.port.approved("c1"))
        sha = git(self.origin, "rev-parse", "orch/p7/api").strip()
        self.assertEqual(git(self.origin, "show", "--name-only", "--format=", sha).split(), [])  # no file
        self.assertEqual(git(self.origin, "log", "-1", "--format=%s", sha).strip(),
                         "#41 api: Registration of api failed (plan 7)")
        self.assertEqual(self.github.posts, ["5"])
        meta = talk.read(self.github.comments["5"][0])
        self.assertEqual((meta["kind"], meta["n"], meta["sha"], meta["from"]), ("question", 1, sha, "child"))
        self.assertIn("issue #41 says scope ['app/'], the brief says ['app/orders.py']",
                      self.github.comments["5"][0]["body"])


if __name__ == "__main__":
    unittest.main()
