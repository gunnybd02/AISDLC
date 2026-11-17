"""The shared helpers of utils/contracts.py, each the one owner of its job (owners net): the clock, the session of an
MCP action, and the turning of a step's refusal into the action's error."""
import time
import unittest

from harness.utils.contracts import NO_SESSION, ActionContext, ActionError, answered, now, session_of


class ContractsTest(unittest.TestCase):
    def test_now_is_milliseconds_since_the_epoch(self):
        before = int(time.time() * 1000)
        self.assertTrue(before <= now() <= int(time.time() * 1000))

    def test_session_of_gives_the_session_or_refuses(self):
        self.assertEqual(session_of(ActionContext({"session": lambda: "s1"})), "s1")
        with self.assertRaisesRegex(ActionError, NO_SESSION):
            session_of(ActionContext({"session": lambda: ""}))

    def test_answered_turns_a_listed_refusal_into_the_actions_error(self):
        self.assertEqual(answered((ValueError,), lambda: "done"), "done")

        def refuse():
            raise ValueError("not now")
        with self.assertRaisesRegex(ActionError, "^not now$"):
            answered((ValueError,), refuse)

        def crash():
            raise KeyError("x")
        with self.assertRaises(KeyError):  # a fault that is no refusal goes through
            answered((ValueError,), crash)


if __name__ == "__main__":
    unittest.main()
