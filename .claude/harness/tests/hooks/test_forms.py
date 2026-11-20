"""The answers of a form (hooks/forms.py): a multi-select answer, which Claude Code may give as a list of labels,
reaches the gates as the labels joined by ", " (live run 7: the remove checklist's answer never reached them)."""
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.hooks.forms import Answers, given, label
from harness.utils.contracts import Event, Verdict
from harness.tests.e2e import copy_tree

Q = "Remove the child sessions of plan 37 [r2e69c7aa3486]?"
FORM = {"questions": [{"question": Q, "header": "Remove", "multiSelect": True,
                       "options": [{"label": "hello", "description": "forgotten"}, {"label": "api", "description": "x"},
                                   {"label": "Keep all", "description": "archive none"}]}]}


def answered(response):
    """The PostToolUse of the checklist with this response."""
    return Event("PostToolUse", "AskUserQuestion", FORM, "s1", "/w", response)


class MultiSelectTest(unittest.TestCase):
    def test_a_list_of_labels_reads_as_one_text(self):
        """s2.forms.multi-select: a list joins with ", "; a plain label stays; anything else is no answer."""
        self.assertEqual(label(["hello"]), "hello")
        self.assertEqual(label(["hello", "api"]), "hello, api")
        self.assertEqual(label("hello"), "hello")
        for odd in ([], [1], {"a": 1}, None, True):
            with self.subTest(odd=odd):
                self.assertIsNone(label(odd))
        for response in ({"answers": {Q: ["hello", "api"]}}, {"questions": FORM["questions"],
                                                              "answers": {Q: ["hello", "api"]}},
                         '{"answers": {"' + Q + '": ["hello", "api"]}}', {"answers": {Q: "hello, api"}}):
            with self.subTest(response=str(response)[:40]):
                self.assertEqual(given(answered(response)), {Q: "hello, api"})

    def test_through_the_hook_the_ticked_child_gets_its_remove_pass(self):
        """s2.forms.multi-select: the hook's Act writes the one-use pass of exactly the ticked child."""
        port = LedgerPort(copy_tree(self))
        port.touch_session("s1")
        event = answered({"answers": {Q: ["hello"]}})
        notes = Act(port).run(event, Answers().translate(event), Verdict("allow"))
        self.assertTrue(any(n.startswith("GATE: the user ticked hello to remove [r2e69c7aa3486]") for n in notes))
        keys = [r["key"] for r in port.rows("SELECT key FROM pl_asks WHERE used = 0")]
        self.assertEqual(keys, ["r2e69c7aa3486:hello"])


if __name__ == "__main__":
    unittest.main()
