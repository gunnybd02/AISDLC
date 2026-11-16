import unittest

from echo import echo


class EchoTest(unittest.TestCase):
    def test_ac1_repeats_text(self):
        """AC1: echo('ab', 3) returns 'ababab'"""
        # behaviour p1.echo.ac1
        self.assertEqual(echo("ab", 3), "ababab")

    def test_ac2_times_below_one_raises(self):
        """AC2: echo with times below one raises ValueError"""
        # behaviour p1.echo.ac2
        for times in (0, -1):
            with self.assertRaises(ValueError):
                echo("ab", times)


if __name__ == "__main__":
    unittest.main()
