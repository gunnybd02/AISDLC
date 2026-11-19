"""Acceptance test of the child hello (live run), written and locked by the orchestrator: the child makes it pass and
never changes it."""
import unittest

from hello import hello


class HelloAcceptance(unittest.TestCase):
    def test_ac1_greets_by_name(self):
        """AC1: hello("Ann") returns "Hello, Ann"."""
        self.assertEqual(hello("Ann"), "Hello, Ann")

    def test_ac2_refuses_an_empty_name(self):
        """AC2: hello("") raises ValueError."""
        self.assertRaises(ValueError, hello, "")


if __name__ == "__main__":
    unittest.main()
