import unittest

from shout import shout


class ShoutTest(unittest.TestCase):
    def test_ac1_hi_becomes_capitals_with_bang(self):
        # AC1 (p1.shout.ac1): shout('hi') returns 'HI!'
        self.assertEqual(shout("hi"), "HI!")

    def test_ac2_empty_text_returns_bang(self):
        # AC2 (p1.shout.ac2): shout of an empty text returns '!'
        self.assertEqual(shout(""), "!")


if __name__ == "__main__":
    unittest.main()
