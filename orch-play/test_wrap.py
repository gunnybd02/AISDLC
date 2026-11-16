import unittest

from wrap import wrap


class WrapTest(unittest.TestCase):
    def test_ac1_wraps_text_in_mark(self):
        """AC1: wrap('hi', '*') returns '*hi*'"""
        # behaviour p1.wrap.ac1
        self.assertEqual(wrap("hi", "*"), "*hi*")

    def test_ac2_empty_mark_raises(self):
        """AC2: wrap with an empty mark raises ValueError"""
        # behaviour p1.wrap.ac2
        with self.assertRaises(ValueError):
            wrap("hi", "")


if __name__ == "__main__":
    unittest.main()
