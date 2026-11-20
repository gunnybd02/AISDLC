"""Locked acceptance tests of the farewell child (live run 11)."""
import unittest

from farewell import farewell


class T(unittest.TestCase):
    def test_ac1(self):
        """AC1: farewell("Ann") returns "Bye, Ann"."""
        self.assertEqual(farewell("Ann"), "Bye, Ann")

    def test_ac2(self):
        """AC2: farewell("") raises ValueError."""
        self.assertRaises(ValueError, farewell, "")


if __name__ == "__main__":
    unittest.main()
