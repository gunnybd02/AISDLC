"""h8.state-shut: every place a shell line names, read or written, is found, from every folder it may run in."""
import unittest

from harness.utils.shell.mentions import mentioned
from tests import tree


class MentionsTest(unittest.TestCase):
    def setUp(self):
        self.home = tree(self, {"s/h.db": "", "s/h.db-wal": ""})
        self.cwd = str(self.home).replace("\\", "/")

    def found(self, line, dialect="bash"):
        return [p[len(self.cwd) + 1:] for p in mentioned(line, dialect, self.cwd) if p.startswith(self.cwd + "/")]

    def test_words_redirections_option_values_and_variables_are_places(self):
        self.assertEqual(self.found("A=s/x sort --output=s/o -k1 s/h.db > s/r"), ["s/h.db", "s/o", "s/r", "s/x"])

    def test_a_wildcard_is_expanded_against_the_disk(self):
        self.assertEqual(self.found("cat s/h.d*"), ["s/h.db", "s/h.db-wal"])

    def test_after_cd_a_path_is_read_from_both_folders(self):
        self.assertIn("s/h.db", self.found("cd s && cat h.db"))

    def test_a_line_the_reader_cannot_see_whole_is_read_word_by_word(self):
        self.assertIn("s/h.db", self.found("cat <(sqlite3 s/h.db .dump)"))

    def test_a_word_the_shell_makes_is_left_out(self):
        self.assertEqual(self.found("cat $D/h.db"), [])

    def test_the_harness_own_commands_name_nothing(self):
        self.assertEqual(self.found("HARNESS_DB=s/h.db python3 -m entry.cli verify"), [])
        self.assertEqual(self.found("python3 .claude/entry/doctor.py s/h.db"), [])


if __name__ == "__main__":
    unittest.main()
