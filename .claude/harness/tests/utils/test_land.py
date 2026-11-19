"""orchestra part 3, the final route: land merges the accepted pull requests (a fake GitHub that merges on the real
origin), runs the unit's tests on the merged base and closes the delegated plan delivered; a conflict stops it with
the two ways on; it waits while a child runs and for the parent's own files."""
import unittest

from harness.utils.orchestra import land, review
from harness.utils.plan import tickets

land.WAIT = 0  # the tests do not wait for GitHub
from harness.tests import tree
from harness.tests.utils.test_review import (LOCKED_UNITS, URL, UNITS, FakeGitHub, LockedScenario, Scenario, git)


class PlanGitHub:
    """GitHub REST for a plan with a plan branch: each pull request merges its head into its own base on the real
    origin, through a clone of its own; the user's merge of the plan pull request is merge(n)."""

    def __init__(self, origin, folder, drafts=None):
        self.origin, self.folder, self.calls = origin, folder, []
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
        n = int(path.split("/")[4])  # repos/o/r/pulls/<n>[/merge]
        if method == "GET":
            return {"merged": self.prs[n]["merged"], "mergeable": True}
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
    def test_children_land_on_the_plan_branch_and_only_the_users_merge_delivers(self):
        """s5.accept.plan-branch, s5.land.plan-pr, s5.land.delivered: the child's draft #5 (spawn) is made ready."""
        github = PlanGitHub(self.origin, tree(self, {}), {5: (f"orch/p{self.plan}/hello", f"plan/p{self.plan}")})
        self.hand_back()
        self.assertIn("Green", review.check(self.port, "s1", "hello", LOCKED_UNITS, []))
        self.assertIn(f"from orch/p{self.plan}/hello into plan/p{self.plan}",
                      review.accept(self.port, "s1", "hello", LOCKED_UNITS, github))
        self.port.write(lambda con, rec: tickets.save(con, {**self.port.ticket("s1"), "phase": "deliver"}))
        text = land.land(self.port, "s1", LOCKED_UNITS, [], github)
        self.assertIn(f"Merged #5 of hello into plan/p{self.plan}", text)
        self.assertIn(f"on the merged plan/p{self.plan}: green", text)
        self.assertIn(f"Plan pull request #6 ({URL}/pull/6): plan/p{self.plan} into work", text)
        self.assertIn("the harness refuses it with the form question until the user allows it", text)
        self.assertEqual(self.port.ticket("s1")["state"], "open")
        self.assertNotIn("orch-probe/hello.py", git(self.origin, "ls-tree", "-r", "--name-only", "work"))
        self.assertIn("Plan pull request #6", land.land(self.port, "s1", LOCKED_UNITS, [], github))  # still waits
        github.merge(6)  # the user's merge
        text = land.land(self.port, "s1", LOCKED_UNITS, [], github)
        self.assertIn("The plan pull request #6 is merged into work", text)
        self.assertIn("is delivered", text)
        self.assertEqual(self.port.ticket("s1")["state"], "closed")
        self.assertIn("orch-probe/hello.py", git(self.origin, "ls-tree", "-r", "--name-only", "work"))
        self.assertEqual([c[2]["base"] for c in github.calls if c[1].endswith("/pulls")], ["work"])  # the plan PR
        self.assertEqual([c[1] for c in github.calls if c[0] == "POST"], ["graphql", "repos/o/r/pulls"])


class LandTest(Scenario):
    def accepted(self, github):
        self.hand_back()
        review.check(self.port, "s1", "hello", UNITS, [])
        review.accept(self.port, "s1", "hello", UNITS, github)

    def test_land_merges_tests_the_merged_base_and_delivers(self):
        github = FakeGitHub(self.repo)
        with self.assertRaisesRegex(review.ReviewError, "have not ended: hello"):
            land.land(self.port, "s1", UNITS, [], github)
        self.accepted(github)
        text = land.land(self.port, "s1", UNITS, [], github)
        self.assertIn("Merged #5 of hello into work", text)
        self.assertIn("on the merged work: green", text)
        self.assertIn("waits for your own files (notes.md)", text)  # the parent's own file is not committed yet
        self.assertTrue(self.port.ticket("s1")["crew"]["hello"]["merged"]["sha"])
        self.assertIn("orch-probe/hello.py", git(self.origin, "ls-tree", "-r", "--name-only", "work"))
        self.port.write(lambda con, rec: __import__("harness.utils.plan.tickets", fromlist=["x"]).save(
            con, {**self.port.ticket("s1"), "phase": "deliver"}))  # as after the parent's own step_done
        text = land.land(self.port, "s1", UNITS, [], github)
        self.assertIn("is delivered", text)
        self.assertEqual(self.port.ticket("s1")["state"], "closed")
        self.assertEqual(len([c for c in github.calls if c[0] == "PUT"]), 1)  # merged once
        self.assertIn("Delete the check-in", text)

    def test_a_conflict_stops_land_with_the_two_ways_on(self):
        github = FakeGitHub(self.repo, conflict=True)
        self.accepted(github)
        (self.repo / "orch-probe").mkdir()
        (self.repo / "orch-probe" / "hello.py").write_text("other = 1\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base moves")
        git(self.repo, "push", "-q", "origin", "work")
        text = land.land(self.port, "s1", UNITS, [], github)
        self.assertIn("does not merge into work", text)
        self.assertIn("Conflicts in: orch-probe/hello.py", text)
        self.assertIn("run('orchestra', 'reject'", text)
        self.assertEqual(self.port.ticket("s1")["state"], "open")
        self.assertIn("round 1 of 3", review.reject(self.port, "s1", "hello", "conflicts with work", UNITS, 3))

    def test_a_refusal_with_a_clean_local_merge_is_not_called_a_conflict(self):
        github = FakeGitHub(self.repo, conflict=True)
        self.accepted(github)
        text = land.land(self.port, "s1", UNITS, [], github)
        self.assertIn("merges cleanly here, but GitHub refused it", text)
        self.assertNotIn("Resolve it here", text)

    def test_what_a_card_covers(self):
        card = {"change": ["src/", "a.py"], "tests": ["tests/test_*.py"]}
        self.assertEqual([land.covers(card, p) for p in ("src/x.py", "a.py", "tests/test_a.py", "b.py")],
                         [True, True, True, False])


if __name__ == "__main__":
    unittest.main()
