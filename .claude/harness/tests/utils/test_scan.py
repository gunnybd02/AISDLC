"""h13.shell-read: a shell line becomes the commands that really run, with their words, redirections and heredocs; the
wrappers (sudo, env, xargs, sh -c, eval, powershell -Command, cmd /c...) are taken off; a line the reader cannot see
whole says why, and gives no command."""
import unittest

from harness.utils.shell.scan import scan
from harness.utils.shell.words import DEPTH, read


def names(text, dialect="bash"):
    line = read(text, dialect)
    return [c.name for c in line.commands], line.unread


def args(text, dialect="bash"):
    (command,) = read(text, dialect).commands
    return [w.text for w in command.args]


class ScanTest(unittest.TestCase):
    def test_separators_end_a_command(self):
        self.assertEqual(names("a; b && c || d | e & f\ng |& h"), (list("abcdefgh"), []))

    def test_quotes_and_escapes_are_read_as_bash_reads_them(self):
        self.assertEqual(args("echo 'a b' \"c d\" e\\ f \"g\\\"h\" 'i\\j' C:\\x"),
                         ["a b", "c d", "e f", 'g"h', "i\\j", "C:x"])
        self.assertEqual(names("echo 'a;b' \"c && d\""), (["echo"], []))
        self.assertEqual(args("echo a\\\nb"), ["ab"])

    def test_a_word_whose_value_the_shell_makes_is_dynamic(self):
        (command,) = read("echo $HOME \"$X\" '$Y' *.py a?c [ab] ~/x {a,b} plain").commands
        self.assertEqual([w.dynamic for w in command.args], [True, True, False, True, True, True, True, True, False])

    def test_what_runs_another_command_inside_a_word_is_unread(self):
        for text in ("echo $(rm x)", "echo `rm x`", "echo \"$(rm x)\"", "diff <(ls) b", "tee >(cat) x",
                     "(cd x && rm y)", "{ rm x; }", "echo $'a'", "echo $((1+2))", "case x in a) ;; esac"):
            with self.subTest(text=text):
                line = read(text)
                self.assertEqual(line.commands, [])
                self.assertTrue(line.unread)

    def test_redirections_are_kept_with_their_targets(self):
        (command,) = read("cat a > b 2>&1 >> c &> d < e 3>| f &>> g").commands
        self.assertEqual([w.text for w in command.args], ["a"])
        self.assertEqual([(op, w.text) for op, w in command.redirects],
                         [(">", "b"), (">&", "1"), (">>", "c"), ("&>", "d"), ("<", "e"), (">|", "f"), ("&>>", "g")])

    def test_a_heredoc_body_belongs_to_the_command_that_opened_it(self):
        line = read("cat > f <<EOF\nline; rm x\nEOF\nls")
        self.assertEqual([c.name for c in line.commands], ["cat", "ls"])
        self.assertEqual(line.commands[0].heredoc, "line; rm x\n")
        self.assertEqual(read("cat <<'EOF'\n$(rm x)\nEOF").commands[0].heredoc, "$(rm x)\n")
        self.assertEqual(read("cat <<-EOF\n\tbody\n\tEOF").commands[0].heredoc, "body\n")

    def test_a_heredoc_that_runs_code_or_never_ends_is_unread(self):
        for text in ("cat <<EOF\n$(rm x)\nEOF", "cat <<EOF\n`rm x`\nEOF", "cat <<EOF\nno end"):
            with self.subTest(text=text):
                self.assertTrue(read(text).unread)

    def test_a_comment_is_no_command(self):
        self.assertEqual(names("ls # ; rm x"), (["ls"], []))
        self.assertEqual(args("echo a#b"), ["a#b"])

    def test_a_quote_left_open_is_unread(self):
        for text in ("echo 'a", 'echo "a', "echo a\\"):
            with self.subTest(text=text):
                self.assertTrue(read(text).unread)

    def test_assignments_before_a_command_are_its_environment(self):
        (command,) = read("A=1 B=$X rm x").commands
        self.assertEqual((command.env, command.name), (["A=1", "B=$X"], "rm"))
        self.assertEqual(read("A=1").commands[0].name, "")


    def test_the_scanner_keeps_the_wrappers_that_read_takes_off(self):
        self.assertEqual([c.name for c in scan("sudo rm x | bash -c 'ls'")], ["sudo", "bash"])


if __name__ == "__main__":
    unittest.main()
