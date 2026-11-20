"""orchestra part 3, the final route: land merges the accepted pull requests (a fake GitHub that merges on the real
origin), runs the unit's tests on the merged base and closes the delegated plan delivered; a conflict stops it with
the two ways on; it waits while a child runs and for the parent's own files."""
import re
import unittest

from harness.assemble.engine.runner import Act
from harness.utils.contracts import Event, Verdict
from harness.utils.git.github import GitHubError
from harness.utils.orchestra import land, review
from harness.utils.plan import tickets

land.WAIT = 0  # the tests do not wait for GitHub
from harness.tests import tree
from harness.tests.utils.test_review import (LOCKED_UNITS, URL, UNITS, FakeGitHub, LockedScenario, Scenario, git)


class PlanGitHub:
    """GitHub REST for a plan with a plan branch: each pull request merges its head into its own base on the real
    origin, through a clone of its own; the user's merge of the plan pull request is merge(n)."""

    def __init__(self, origin, folder, drafts=None, keep=()):
        self.origin, self.folder, self.calls, self.keep = origin, folder, [], keep
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
        n = int(path.split("/")[4])  # repos/o/r/pulls/<n>[/merge]
        if method == "GET":
            head = git(self.origin, "rev-parse", self.prs[n]["head"]).strip()
            return {"merged": self.prs[n]["merged"], "mergeable": True, "head": {"sha": head}}
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
        self.assertIn("Green", self.check())
        self.assertIn(f"from orch/p{self.plan}/hello into plan/p{self.plan}",
                      review.accept(self.port, "s1", "hello", LOCKED_UNITS, github))
        self.port.write(lambda con, rec: tickets.save(con, {**self.port.ticket("s1"), "phase": "deliver"}))
        text = land.land(self.port, "s1", LOCKED_UNITS, [], github)
        self.assertIn(f"Merged #5 of hello into plan/p{self.plan}", text)
        self.assertIn(f"on the merged plan/p{self.plan}: green", text)
        self.assertIn(f"Plan pull request #6 ({URL}/pull/6): plan/p{self.plan} into work, not merged yet", text)
        self.assertIn("Ask the user form 2 now", text)
        self.assertEqual(self.port.ticket("s1")["state"], "open")
        self.assertNotIn("orch-probe/hello.py", git(self.origin, "ls-tree", "-r", "--name-only", "work"))
        q = re.search(r"exactly:\n(.+)\nOptions", land.land(self.port, "s1", LOCKED_UNITS, [], github)).group(1)
        self.assertTrue(q.startswith(f"End plan {self.plan}: merge plan/p{self.plan} into work (PR #6 at "))
        self.assertIn(f"delete 2 branches (orch/p{self.plan}/hello, plan/p{self.plan}), archive 1 child sessions", q)
        answer = Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": q}]}, "s1", "/w")
        notes = Act(self.port).run(answer, {"answers": {q: "Allow"}}, Verdict("allow"))
        self.assertTrue(any(n.startswith("GATE: the user allows form 2") for n in notes))
        self.assertIn("Form 2 is allowed. Merge PR #6 of o/r with the merge tool, expectedHeadSha",
                      land.land(self.port, "s1", LOCKED_UNITS, [], github))
        github.merge(6)  # the merge the gate let through
        text = land.land(self.port, "s1", LOCKED_UNITS, [], github)
        self.assertIn("The plan pull request #6 is merged into work", text)
        self.assertIn(f"Deleted the branches orch/p{self.plan}/hello, plan/p{self.plan}.", text)
        self.assertIn('Archive the child session session_child0001 now: mcp__claude-code-remote__archive_session '
                      '{"session_id": "session_child0001"}', text)
        self.assertIn("is delivered", text)
        self.assertEqual(self.port.ticket("s1")["state"], "closed")
        self.assertIn("orch-probe/hello.py", git(self.origin, "ls-tree", "-r", "--name-only", "work"))
        self.assertEqual([c[2]["base"] for c in github.calls if c[1].endswith("/pulls")], ["work"])  # the plan PR
        self.assertEqual([c[1] for c in github.calls if c[0] == "POST"], ["graphql", "repos/o/r/pulls"])

    def test_after_the_plan_pr_merged_land_cleans_up_and_names_a_branch_it_cannot_delete(self):
        """s6.end.cleanup: every child session is archived (earlier ones too); a kept branch is named for the user."""
        github = PlanGitHub(self.origin, tree(self, {}), {5: (f"orch/p{self.plan}/hello", f"plan/p{self.plan}")},
                            keep=(f"plan/p{self.plan}",))
        self.hand_back()
        self.check()
        review.accept(self.port, "s1", "hello", LOCKED_UNITS, github)
        team = self.port.ticket("s1")["crew"]
        team["hello"]["sessions"] = ["session_child_old"]  # a send-back opened a fresh session once
        self.port.write(lambda con, rec: tickets.save(con, {**self.port.ticket("s1"), "crew": team, "phase": "deliver"}))
        q = re.search(r"exactly:\n(.+)\nOptions", land.land(self.port, "s1", LOCKED_UNITS, [], github)).group(1)
        self.assertIn("archive 2 child sessions", q)
        Act(self.port).run(Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": q}]}, "s1", "/w"),
                           {"answers": {q: "Allow"}}, Verdict("allow"))
        github.merge(6)
        text = land.land(self.port, "s1", LOCKED_UNITS, [], github)
        self.assertIn(f"Deleted the branches orch/p{self.plan}/hello.", text)
        self.assertIn(f"GitHub kept plan/p{self.plan} (", text)
        for sid in ("session_child_old", "session_child0001"):
            self.assertIn(f'{{"session_id": "{sid}"}}', text)
        self.assertEqual(self.port.ticket("s1")["state"], "closed")

    def test_land_ends_with_no_step_of_the_parent_when_its_only_files_are_the_locked_tests(self):
        """s3.land.locked-not-own: live run 6 waited for the parent's own files: the locked test lock had shipped."""
        self.assertEqual(land.own_files({"plan": {"files": ["orch-probe/test_hello_ac.py", "notes.md"], "children": [
            {"name": "hello", "change": ["orch-probe/hello.py"], "acTests": ["orch-probe/test_hello_ac.py"]}]}}),
            ["notes.md"])
        github = PlanGitHub(self.origin, tree(self, {}), {5: (f"orch/p{self.plan}/hello", f"plan/p{self.plan}")})
        self.hand_back()
        self.check()
        review.accept(self.port, "s1", "hello", LOCKED_UNITS, github)
        ticket = self.port.ticket("s1")
        only = {**ticket["plan"], "files": ["orch-probe/test_hello_ac.py"]}  # the run plan: only the locked test
        self.port.write(lambda con, rec: tickets.save(con, {**ticket, "plan": only}))
        q = re.search(r"exactly:\n(.+)\nOptions", land.land(self.port, "s1", LOCKED_UNITS, [], github)).group(1)
        Act(self.port).run(Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": q}]}, "s1", "/w"),
                           {"answers": {q: "Allow"}}, Verdict("allow"))
        github.merge(6)
        text = land.land(self.port, "s1", LOCKED_UNITS, [], github)
        self.assertNotIn("waits for your own files", text)
        self.assertIn("is delivered", text)
        self.assertNotEqual(self.port.ticket("s1").get("phase"), "deliver")  # no step_done of the parent was needed


class LandTest(Scenario):
    def accepted(self, github):
        self.hand_back()
        self.check()
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
        self.assertIn("round 1 of 3", review.reject(self.port, "s1", "hello", "conflicts with work", 3, github))

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
