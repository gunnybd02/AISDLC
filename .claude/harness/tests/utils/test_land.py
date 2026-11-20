"""orchestra part 3: accept merges each green child into its base at the tested commit (a fake GitHub that merges
on the real origin); close ends the delegated plan when every child is merged or forgotten, with no form 2."""
import unittest

from harness.utils.contracts import Event
from harness.utils.orchestra import land, review
from harness.utils.plan import tickets
from harness.tests import tree
from harness.tests.utils.test_review import (LOCKED_UNITS, URL, UNITS, FakeGitHub, LockedScenario, Scenario, git)


class PlanGitHub:
    """GitHub REST for a plan with a plan branch: each pull request merges its head into its own base on the real
    origin, through a clone of its own; the user's merge of the plan pull request is merge(n)."""

    def __init__(self, origin, folder, drafts=None, keep=()):
        self.origin, self.folder, self.calls, self.keep, self.comments = origin, folder, [], keep, []
        self.prs = {n: {"head": head, "base": base, "merged": False} for n, (head, base) in (drafts or {}).items()}
        git(folder, "clone", "-q", str(origin), ".")
        git(folder, "config", "user.name", "u")
        git(folder, "config", "user.email", "u@u")

    def __call__(self, method, path, fields=None):
        self.calls.append((method, path, dict(fields or {})))
        if path == "graphql":  # a draft made ready
            return {"data": {"markPullRequestReadyForReview": {"pullRequest": {"isDraft": False}}}}
        if method == "POST":
            n = 5 + len(self.prs)
            self.prs[n] = {"head": fields["head"], "base": fields["base"], "merged": False}
            return {"number": n, "html_url": f"{URL}/pull/{n}"}
        if method == "DELETE":  # repos/o/r/git/refs/heads/<ref>: a branch deleted, unless kept
            ref = path.split("/refs/heads/", 1)[1]
            if ref in self.keep:
                raise GitHubError("gh api DELETE: Reference does not exist (HTTP 422)")
            git(self.origin, "branch", "-D", ref)
            return {}
        if method == "GET" and "/check-runs" in path:  # the project's CI: none here
            return {"check_runs": []}
        if method == "GET" and path.endswith("/status"):
            return {"state": "pending", "statuses": [], "total_count": 0}
        if method == "GET" and path.split("?")[0].endswith("/comments"):
            return list(self.comments)
        n = int(path.split("/")[4])  # repos/o/r/pulls/<n>[/merge]
        if method == "GET":
            head = git(self.origin, "rev-parse", self.prs[n]["head"]).strip()
            return {"merged": self.prs[n]["merged"], "mergeable": True, "head": {"sha": head},
                    "base": {"ref": self.prs[n]["base"]}, "draft": False}
        return {"sha": self.merge(n)}

    def merge(self, n):
        pr = self.prs[n]
        git(self.folder, "fetch", "-q", "origin")
        git(self.folder, "switch", "-q", "-C", pr["base"], f"origin/{pr['base']}")
        git(self.folder, "merge", "-q", "--no-ff", "-m", f"merge #{n}", f"origin/{pr['head']}")
        git(self.folder, "push", "-q", "origin", pr["base"])
        pr["merged"] = True
        return git(self.folder, "rev-parse", "HEAD").strip()


class LockedLandTest(LockedScenario):
    def test_a_locked_child_merges_at_accept_and_close_delivers_without_form_2(self):
        """s5.close.ends: accept merges the child into its base; close delivers with no form 2 and gives the archive
        call; the locked test alone is no own file of the parent."""
        self.assertEqual(land.own_files({"plan": {"files": ["orch-probe/test_hello_ac.py", "notes.md"], "children": [
            {"name": "hello", "change": ["orch-probe/hello.py"], "acTests": ["orch-probe/test_hello_ac.py"]}]}}),
            ["notes.md"])
        github = PlanGitHub(self.origin, tree(self, {}), {5: (f"orch/p{self.plan}/hello", f"plan/p{self.plan}")})
        self.hand_back()
        self.assertIn("Green", self.check())
        self.assertIn(f"accepted and merged: #5 into plan/p{self.plan}",
                      land.accept(self.port, "s1", "hello", LOCKED_UNITS, github))
        ticket = self.port.ticket("s1")
        only = {**ticket["plan"], "files": ["orch-probe/test_hello_ac.py"]}  # the run plan: only the locked test
        self.port.write(lambda con, rec: tickets.save(con, {**ticket, "plan": only}))
        text = land.close(self.port, "s1")
        self.assertIn("is delivered: every child is merged or forgotten", text)
        self.assertIn('archive_session {"session_id": "session_child0001"}', text)
        self.assertNotIn("form 2", text)
        self.assertEqual(self.port.ticket("s1")["state"], "closed")
        self.assertEqual([c[1] for c in github.calls if c[0] == "POST"], [])  # no plan pull request is opened


class LandTest(Scenario):
    def test_accept_merges_at_the_tested_commit_and_tells_the_child_to_stop(self):
        """s4.accept.merge: a moved head or another base is refused; the merge names the tested sha; the merge tool
        on that pull request still needs the user's Allow."""
        from harness.gear.translate.merge import MergeCalls
        from harness.utils.forge import merges
        github = FakeGitHub(self.repo, comments=self.said)
        with self.assertRaisesRegex(review.ReviewError, "has not passed a check"):
            land.accept(self.port, "s1", "hello", UNITS, github)
        self.hand_back()
        self.assertIn("Green", self.check())
        tested = self.port.ticket("s1")["crew"]["hello"]["lastCheck"]["sha"]
        github.base = "main"
        with self.assertRaisesRegex(review.ReviewError, "goes into main, not work"):
            land.accept(self.port, "s1", "hello", UNITS, github)
        github.base = "work"
        self.hand_back()  # a new push after the check
        with self.assertRaisesRegex(review.ReviewError, "moved since the check"):
            land.accept(self.port, "s1", "hello", UNITS, github)
        self.assertIn("Green", self.check())
        tested = self.port.ticket("s1")["crew"]["hello"]["lastCheck"]["sha"]
        text = land.accept(self.port, "s1", "hello", UNITS, github)
        self.assertIn(f"accepted and merged: #5 into work at {tested[:12]}", text)
        self.assertIn('archive_session {"session_id": "session_child0001"}', text)
        (_, path, fields), = [c for c in github.calls if c[0] == "PUT"]
        self.assertEqual((path, fields["sha"], fields["merge_method"]), ("repos/o/r/pulls/5/merge", tested, "merge"))
        self.assertIn("orch-probe/hello.py", git(self.origin, "ls-tree", "-r", "--name-only", "work"))
        entry = self.port.ticket("s1")["crew"]["hello"]
        self.assertEqual((entry["state"], bool(entry["merged"]["sha"])), ("accepted", True))
        call = {"owner": "o", "repo": "r", "pullNumber": 5, "expectedHeadSha": tested}
        acts = MergeCalls().translate(Event("PreToolUse", "mcp__github__merge_pull_request", call, "s1"),
                                      {"merge_pass": lambda code: merges.held(self.port, code)})
        self.assertEqual(acts["rule_actions"][0]["op"], "no_pass")  # no pass was written by accept

    def test_close_waits_for_every_child_and_the_parents_own_files(self):
        """s5.close.ends: refused while a child is neither merged nor forgotten; then it waits for the parent's own
        files; then delivered, with no form 2."""
        github = FakeGitHub(self.repo, comments=self.said)
        with self.assertRaisesRegex(review.ReviewError, "neither merged nor forgotten: hello"):
            land.close(self.port, "s1")
        self.hand_back()
        self.check()
        land.accept(self.port, "s1", "hello", UNITS, github)
        self.assertIn("waits for your own files (notes.md)", land.close(self.port, "s1"))
        self.port.write(lambda con, rec: tickets.save(con, {**self.port.ticket("s1"), "phase": "deliver"}))
        text = land.close(self.port, "s1")
        self.assertIn("is delivered", text)
        self.assertIn("Delete the check-in", text)
        self.assertEqual(self.port.ticket("s1")["state"], "closed")
        self.assertEqual(len([c for c in github.calls if c[0] == "PUT"]), 1)  # merged once, at accept

    def test_a_forgotten_child_does_not_hold_close(self):
        """s5.close.ends: a forgotten child ends the plan as well as a merged one."""
        review.forget(self.port, "s1", "hello", "it will not come back")
        self.port.write(lambda con, rec: tickets.save(con, {**self.port.ticket("s1"), "phase": "deliver"}))
        self.assertIn("is delivered", land.close(self.port, "s1"))

    def test_what_a_card_covers(self):
        card = {"change": ["src/", "a.py"], "tests": ["tests/test_*.py"]}
        self.assertEqual([land.covers(card, p) for p in ("src/x.py", "a.py", "tests/test_a.py", "b.py")],
                         [True, True, True, False])


if __name__ == "__main__":
    unittest.main()
