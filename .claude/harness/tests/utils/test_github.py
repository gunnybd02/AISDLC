"""The GitHub call (utils/git/github.py): the gh command it runs, with each field sent as GitHub wants its type."""
import unittest

from harness.utils.git.github import repo_of, words_of


class GitHubTest(unittest.TestCase):
    def test_a_bool_or_number_is_typed_and_text_stays_text(self):
        """s1.github.typed: draft true reaches GitHub as a bool, not as the text "true"."""
        words = words_of("POST", "repos/o/r/pulls", {"head": "orch/p7/api", "draft": True, "maintainer": False,
                                                     "number": 41, "title": "[p7] api: true"})
        self.assertEqual(words, ["gh", "api", "-X", "POST", "repos/o/r/pulls", "-f", "head=orch/p7/api",
                                 "-F", "draft=true", "-F", "maintainer=false", "-F", "number=41",
                                 "-f", "title=[p7] api: true"])
        self.assertEqual(words_of("GET", "repos/o/r/pulls/5"), ["gh", "api", "-X", "GET", "repos/o/r/pulls/5"])
        self.assertEqual(repo_of("https://github.com/o/r.git"), "o/r")


if __name__ == "__main__":
    unittest.main()
