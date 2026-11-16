"""orchestra part 4: release gives a session back; remove asks ONE checklist and archives exactly what the user ticked
(each tick a one-use pass, read from the form's answer by the hook's Act); digest gives one line per child."""
import json
import unittest

from harness.assemble.engine.runner import Act
from harness.mcp.actions.orchestra import Started
from harness.utils.contracts import ActionContext, Event, Verdict
from harness.utils.orchestra import cleanup, review
from harness.tests.utils.test_review import Scenario


class CleanupTest(Scenario):
    def test_release_gives_the_session_back(self):
        with self.assertRaisesRegex(review.ReviewError, "say why"):
            cleanup.release(self.port, "s1", "hello", " ")
        self.assertIn("the user's again", cleanup.release(self.port, "s1", "hello", "the user wants it"))
        self.assertEqual(self.port.ticket("s1")["crew"]["hello"]["state"], "released")

    def test_remove_asks_one_checklist_and_archives_only_what_was_ticked(self):
        with self.assertRaisesRegex(review.ReviewError, "no child may be removed"):
            cleanup.remove(self.port, "s1")  # hello still runs
        review.forget(self.port, "s1", "hello", "gone")
        text = cleanup.remove(self.port, "s1")
        form = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
        question = form["questions"][0]
        self.assertTrue(question["multiSelect"])
        self.assertEqual([o["label"] for o in question["options"]], ["hello", "Keep all"])  # two choices at least
        self.assertIn("Ask now with AskUserQuestion", cleanup.remove(self.port, "s1"))  # no tick: still the form
        notes = Act(self.port).run(Event("PostToolUse", "AskUserQuestion", {"questions": [question]}, "s1", "/w"),
                                   {"answers": {question["question"]: "hello"}}, Verdict("allow"))
        self.assertIn("the user ticked hello", " ".join(notes))
        done = cleanup.remove(self.port, "s1")
        self.assertIn('archive_session {"session_id": "session_child0001"}', done)
        self.assertEqual(self.port.ticket("s1")["crew"]["hello"]["state"], "removed")
        with self.assertRaisesRegex(review.ReviewError, "no child may be removed"):
            cleanup.remove(self.port, "s1")  # the pass was used once

    def test_keep_all_archives_nothing_and_wins_over_ticks(self):
        review.forget(self.port, "s1", "hello", "gone")
        question = cleanup.checklist(self.port.ticket("s1"))[0]
        for answer in ("Keep all", "hello, Keep all"):
            with self.subTest(answer=answer):
                notes = Act(self.port).run(Event("PostToolUse", "AskUserQuestion", {}, "s1", "/w"),
                                           {"answers": {question["question"]: answer}}, Verdict("allow"))
                self.assertIn("ticked no child", " ".join(notes))
                self.assertIn("Ask now with AskUserQuestion", cleanup.remove(self.port, "s1"))  # asked again later
        self.assertEqual(self.port.ticket("s1")["crew"]["hello"]["state"], "forgotten")

    def test_the_digest_and_the_first_childs_check_in(self):
        line = cleanup.digest(self.port, "s1").splitlines()[1]
        self.assertTrue(line.startswith("hello | running | rounds 0 | session session_child0001 | orch/p"))
        self.assertIn("check - | PR - | not merged", line)
        self.assertEqual(cleanup.digest(self.port, "nobody"), "No delegated plan in this session.")

    def test_only_the_first_started_child_is_told_to_set_the_check_in(self):
        ctx = ActionContext({"plans": self.port, "session": lambda: "s1"})
        review.forget(self.port, "s1", "hello", "again")
        again = Started().run(ctx, {"name": "hello", "sid": "session_child0002"})
        self.assertNotIn("check-in", again)  # the crew had a child already


if __name__ == "__main__":
    unittest.main()
