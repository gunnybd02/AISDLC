import unittest

from trim import trim


class TrimTest(unittest.TestCase):
    def test_ac1_removes_spaces_at_both_ends(self):
        """AC1: trim(' hi ') returns 'hi'"""
        # behaviour p1.trim.ac1
        self.assertEqual(trim(" hi "), "hi")
        self.assertEqual(trim("  a b  "), "a b")

    def test_ac2_not_a_string_raises(self):
        """AC2: trim of a value that is not a string raises TypeError"""
        # behaviour p1.trim.ac2
        for value in (None, 3, [" hi "], b" hi "):
            with self.assertRaises(TypeError):
                trim(value)


if __name__ == "__main__":
    unittest.main()
