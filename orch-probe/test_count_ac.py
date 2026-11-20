"""Locked acceptance tests of the count child (live run 12)."""
import unittest

from count import count_words


class T(unittest.TestCase):
    def test_ac1(self):
        """AC1: count_words("a b c") returns 3."""
        self.assertEqual(count_words("a b c"), 3)

    def test_ac2(self):
        """AC2: count_words("") returns 0."""
        self.assertEqual(count_words(""), 0)


if __name__ == "__main__":
    unittest.main()
