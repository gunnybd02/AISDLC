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

    def test_an_answer_can_be_read_as_text_with_the_same_errors(self):
        """s2.github.text: a job log is plain text; a failing gh raises GitHubError for both kinds of call."""
        import os
        import stat
        from unittest import mock
        from harness.utils.git import github
        from harness.tests import tree
        bin_dir = tree(self, {"gh": '#!/bin/sh\nif [ "$4" = "repos/o/r/actions/jobs/7/logs" ]; then\n'
                                    '  printf "2026-11-19T01:02:03Z FAIL scope: app/x.py\\n"\nelse\n'
                                    '  echo "HTTP 404: Not Found" >&2; exit 1\nfi\n'})
        os.chmod(bin_dir / "gh", os.stat(bin_dir / "gh").st_mode | stat.S_IEXEC)
        with mock.patch.dict(os.environ, {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}):
            self.assertEqual(github.text("GET", "repos/o/r/actions/jobs/7/logs"),
                             "2026-11-19T01:02:03Z FAIL scope: app/x.py\n")
            with self.assertRaisesRegex(github.GitHubError, "is not JSON"):
                github.call("GET", "repos/o/r/actions/jobs/7/logs")
            for read in (github.text, github.call):
                with self.subTest(read=read.__name__), self.assertRaisesRegex(github.GitHubError, "HTTP 404"):
                    read("GET", "repos/o/r/pulls/9")


if __name__ == "__main__":
    unittest.main()
