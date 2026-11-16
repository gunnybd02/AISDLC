import unittest

from hello import hello


class HelloTest(unittest.TestCase):
    def test_ac1_greets_by_name(self):
        self.assertEqual(hello("Ann"), "Hello, Ann")

    def test_ac2_empty_name_raises(self):
        with self.assertRaises(ValueError):
            hello("")


if __name__ == "__main__":
    unittest.main()
