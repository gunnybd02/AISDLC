"""The merge pass (utils/forge/merges.py): the user's Allow to the exact merge question writes a one-use pass for one
pull request at one head commit; a merge tool call that merged uses it, so the next merge asks again."""
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.utils.contracts import Event, Verdict
from harness.utils.forge import merges
from harness.tests.e2e import copy_tree

SHA = "e470516a6e49def66a3f0b0b05a279e81f6d9eec"
CALL = {"owner": "gunnybd02", "repo": "AISDLC", "pullNumber": 76, "expectedHeadSha": SHA}
TOOL = "mcp__github__merge_pull_request"


class MergesTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(copy_tree(self))
        self.port.touch_session("s1")
        self.code = merges.code_of("gunnybd02", "AISDLC", 76, SHA)
        self.q = merges.question("gunnybd02", "AISDLC", 76, SHA)

    def answer(self, question, label):
        event = Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": question}]}, "s1", "/w")
        return Act(self.port).run(event, {"answers": {question: label}}, Verdict("allow"))

    def merge(self, response, given=None):
        return Act(self.port).run(Event("PostToolUse", TOOL, given or CALL, "s1", "/w", response), {}, Verdict("allow"))

    def test_allow_on_the_exact_question_writes_a_one_use_pass(self):
        """s1.merges.allow-pass: Deny, or another question, writes no pass; Allow writes exactly this one."""
        self.assertEqual(self.q, f"Merge PR #76 of gunnybd02/AISDLC at e470516a6e49 [{self.code}]?")
        self.assertEqual(merges.target(CALL), ("gunnybd02", "AISDLC", 76, SHA))
        self.assertEqual(merges.target({**CALL, "expectedHeadSha": "e470516"}), ("gunnybd02", "AISDLC", 76, ""))
        self.assertIsNone(merges.target({"owner": "o", "repo": "r"}))
        self.answer(self.q, "Deny")
        self.answer("Merge request m123 [x]?", "Allow")
        self.assertFalse(merges.held(self.port, self.code))
        notes = self.answer(self.q + "\nThe five fixes of live run 2.", "Allow")  # words after the question are fine
        self.assertTrue(any(n.startswith(f"GATE: the user allows the merge [{self.code}]") for n in notes))
        self.assertTrue(merges.held(self.port, self.code))
        self.assertFalse(merges.held(self.port, merges.code_of("gunnybd02", "AISDLC", 76, "f" * 40)))  # another head
        self.assertFalse(merges.held(self.port, merges.code_of("gunnybd02", "AISDLC", 77, SHA)))  # another PR

    def test_a_merge_that_ran_uses_its_pass(self):
        """s1.merges.used-once: a failed merge keeps the pass; a merge that merged uses it."""
        self.answer(self.q, "Allow")
        self.merge({"message": "Pull Request is not mergeable"})
        self.assertTrue(merges.held(self.port, self.code))
        self.merge('{"sha":"3896","merged":true,"message":"Pull Request successfully merged"}')
        self.assertFalse(merges.held(self.port, self.code))
        self.assertEqual(merges.merged(Event("PostToolUse", TOOL, CALL, "s1", "/w", {"merged": True})), "gunnybd02/aisdlc")
        self.assertEqual(merges.merged(Event("PostToolUse", "Bash", CALL, "s1", "/w", {"merged": True})), "")


if __name__ == "__main__":
    unittest.main()
