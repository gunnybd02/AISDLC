"""The talk (utils/orchestra/talk.py): each side's harness posts its words as one comment ending with the harness
marker; read gives the meta back, newest the newest comment of a child from one side; secrets never leave."""
import json
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.utils.git.github import GitHubError
from harness.utils.orchestra import talk
from harness.tests.e2e import copy_tree

PR = {"repo": "o/r", "number": 5, "url": "https://github.com/o/r/pull/5"}
TOKEN = "ghp_" + "a" * 36


class FakeGitHub:
    """GitHub REST for comments: each POST is kept and answered with an id."""

    def __init__(self, refuse=False):
        self.posts, self.refuse = [], refuse

    def __call__(self, method, path, fields=None):
        if self.refuse:
            raise GitHubError("HTTP 403: refused")
        self.posts.append((method, path, dict(fields or {})))
        n = 900 + len(self.posts)
        return {"id": n, "html_url": f"https://github.com/o/r/pull/5#issuecomment-{n}", "body": fields["body"]}


class TalkTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(copy_tree(self))

    def test_a_comment_carries_its_meta_and_is_kept_by_its_poster(self):
        """s1.talk.one-owner: post writes one comment with the marker; read gives the meta; the ledger keeps it."""
        github = FakeGitHub()
        made = talk.post(self.port, "s1", github, PR, "answer", {"child": "api", "plan": 7, "from": talk.PARENT},
                         ["Use 409 for a closed account."])
        (method, path, fields), = github.posts
        self.assertEqual((method, path), ("POST", "repos/o/r/issues/5/comments"))
        self.assertTrue(fields["body"].startswith("**Answer of the orchestrator** (plan 7)\n\nUse 409"))
        self.assertTrue(fields["body"].endswith(
            '<!-- harness-comment {"child": "api", "from": "orchestrator", "kind": "answer", "plan": 7} -->'))
        self.assertEqual(talk.read(made), {"child": "api", "from": "orchestrator", "kind": "answer", "plan": 7,
                                           "id": 901, "url": made["html_url"]})
        row, = self.port.rows("SELECT key, target, text FROM pl_notes WHERE kind = ?", (talk.SAID,))
        self.assertEqual((row["key"], json.loads(row["text"])["from"]), ("answer", "orchestrator"))
        with self.assertRaises(GitHubError):  # a refused comment is the caller's to handle
            talk.post(self.port, "s1", FakeGitHub(refuse=True), PR, "answer", {"child": "api", "plan": 7}, ["x"])

    def test_read_and_newest_pick_the_harness_comments_of_one_child_and_side(self):
        """s1.talk.one-owner: plain comments and other children are not read; an older comment with no from is the
        child's."""
        def comment(n, meta):
            return {"id": n, "html_url": f"u{n}", "body": "words\n\n" + talk.MARK.format(meta=json.dumps(meta))}
        old = comment(1, {"child": "api", "kind": "question", "plan": 7})  # before from existed
        comments = [old, comment(2, {"child": "api", "kind": "answer", "plan": 7, "from": talk.PARENT}),
                    comment(3, {"child": "web", "kind": "handback", "plan": 7, "from": talk.CHILD}),
                    {"id": 4, "body": "Looks fine to me"}, {"id": 5, "body": "<!-- harness-comment {not json} -->"}]
        self.assertEqual(talk.read(old)["from"], talk.CHILD)
        self.assertIsNone(talk.read(comments[3]))
        self.assertIsNone(talk.read(comments[4]))
        self.assertEqual(talk.newest(comments, "api", ["question", "handback"])["id"], 1)
        self.assertIsNone(talk.newest(comments, "api", ["handback"]))
        self.assertEqual(talk.newest(comments, "api", ["answer"], side=talk.PARENT)["id"], 2)
        self.assertIsNone(talk.newest(comments, "api", ["answer"]))  # the orchestrator's words are not the child's

    def test_a_secret_in_the_words_is_masked_before_it_is_posted(self):
        """s1.talk.mask: the line with the token leaves as [redacted]; the other lines stay."""
        github = FakeGitHub()
        talk.post(self.port, "s1", github, PR, "question", {"child": "api", "plan": 7, "from": talk.CHILD},
                  [f"The deploy needs {TOKEN}", "Which status code?"])
        body = github.posts[0][2]["body"]
        self.assertNotIn(TOKEN, body)
        self.assertIn("[redacted]\n\nWhich status code?", body)
        self.assertLessEqual(len(talk.body_of("handback", {"child": "api"}, ["x" * 70000])), 65536)


if __name__ == "__main__":
    unittest.main()
