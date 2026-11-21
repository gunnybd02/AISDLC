"""Locked acceptance tests of the upper child (live run 13)."""
import unittest

from upper import shout


class T(unittest.TestCase):
    def test_ac1(self):
        """AC1: shout("hi") returns "HI!"."""
        self.assertEqual(shout("hi"), "HI!")

    def test_ac2(self):
        """AC2: shout("") returns "!"."""
        self.assertEqual(shout(""), "!")


if __name__ == "__main__":
    unittest.main()
