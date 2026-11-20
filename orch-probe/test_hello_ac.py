"""Acceptance tests of the child hello (live run 9), locked by the parent."""
import unittest

from hello import hello


class T(unittest.TestCase):
    def test_ac1(self):
        self.assertEqual(hello("Ann"), "Hello, Ann")

    def test_ac2(self):
        self.assertRaises(ValueError, hello, "")


if __name__ == "__main__":
    unittest.main()
