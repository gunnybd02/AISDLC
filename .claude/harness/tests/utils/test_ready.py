"""ready.report: the ready line of each repo of a plan says what its forge answers (reachable, base, issues, protection),
and never fails: a forge that is off, a repository not on GitHub, or a forge that cannot be reached is reported."""
import unittest

from harness.utils.forge.ready import ready_line, report
from harness.utils.git.github import GitHubError

SHOP = {"url": "https://github.com/acme/shop", "base": "main"}


def forge(answers):
    """A fake call(method, path): the answer kept for the path, or a GitHubError for a path it does not know."""
    def call(method, path):
        if path not in answers:
            raise GitHubError(f"gh api {path}: HTTP 404 Not Found")
        return answers[path]
    return call


class ReadyLineTest(unittest.TestCase):
    def test_a_ready_repository_shows_every_fact(self):
        call = forge({"repos/acme/shop": {"has_issues": True}, "repos/acme/shop/branches/main": {"protected": True}})
        self.assertEqual(ready_line("shop", SHOP, call),
                         "Ready: shop | reachable yes | base main exists | issues on | main protected")

    def test_an_unprotected_base_and_issues_off_are_said(self):
        call = forge({"repos/acme/shop": {"has_issues": False}, "repos/acme/shop/branches/dev": {"protected": False}})
        self.assertEqual(ready_line("shop", {**SHOP, "base": "dev"}, call),
                         "Ready: shop | reachable yes | base dev exists | issues off | dev not protected")

    def test_a_missing_base_is_said(self):
        call = forge({"repos/acme/shop": {"has_issues": True}})
        self.assertEqual(ready_line("shop", SHOP, call), "Ready: shop | reachable yes | base main missing | issues on")

    def test_an_unreachable_repository_is_said_with_the_reason(self):
        line = ready_line("shop", SHOP, forge({}))
        self.assertTrue(line.startswith("Ready: shop | not reachable (gh api repos/acme/shop: HTTP 404"), line)

    def test_a_repository_not_on_github_is_not_asked(self):
        self.assertEqual(ready_line("lab", {"url": "https://gitlab.com/acme/lab"}, forge({})),
                         "Ready: lab | not on GitHub: not checked")

    def test_the_forge_off_asks_nothing(self):
        self.assertEqual(ready_line("shop", SHOP, None), "Ready: shop | not checked (the forge is off)")

    def test_the_base_defaults_to_main(self):
        call = forge({"repos/acme/shop": {"has_issues": True}, "repos/acme/shop/branches/main": {"protected": True}})
        self.assertIn("base main exists", ready_line("shop", {"url": SHOP["url"]}, call))


class ReportTest(unittest.TestCase):
    def test_one_line_per_repo_in_the_plans_order(self):
        lines = report({"shop": SHOP, "lab": {"url": "https://gitlab.com/acme/lab"}}, None)
        self.assertEqual(lines, ["Ready: shop | not checked (the forge is off)", "Ready: lab | not on GitHub: not checked"])

    def test_a_plan_without_repos_has_no_line(self):
        self.assertEqual(report(None, None), [])
        self.assertEqual(report({"shop": "not a spec"}, None), [])


if __name__ == "__main__":
    unittest.main()
