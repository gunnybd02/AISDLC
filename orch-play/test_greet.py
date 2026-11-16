import unittest

from greet import greet


class GreetTest(unittest.TestCase):
    def test_ac1_greets_by_name(self):
        """AC1: greet('Ann') returns 'Good day, Ann.'"""
        self.assertEqual(greet("Ann"), "Good day, Ann.")

    def test_ac2_empty_name_raises(self):
        """AC2: greet with an empty name raises ValueError"""
        with self.assertRaises(ValueError):
            greet("")


if __name__ == "__main__":
    unittest.main()
