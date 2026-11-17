"""orchestra part 3, the final route: land merges the accepted pull requests (a fake GitHub that merges on the real
origin), runs the unit's tests on the merged base and closes the delegated plan delivered; a conflict stops it with
the two ways on; it waits while a child runs and for the parent's own files."""
import unittest

from harness.utils.orchestra import land, review

land.WAIT = 0  # the tests do not wait for GitHub
from harness.tests.utils.test_review import UNITS, FakeGitHub, Scenario, git


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
        self.assertIn("round 1 of 3", review.reject(self.port, "s1", "hello", "conflicts with work", UNITS))

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
