"""Locked acceptance tests of the greet child (live run 10)."""
import unittest

from greet import greet


class T(unittest.TestCase):
    def test_ac1(self):
        """AC1: greet("Ann") returns "Hi, Ann"."""
        self.assertEqual(greet("Ann"), "Hi, Ann")

    def test_ac2(self):
        """AC2: greet("") raises ValueError."""
        self.assertRaises(ValueError, greet, "")


if __name__ == "__main__":
    unittest.main()
