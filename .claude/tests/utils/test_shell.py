"""h13.shell-read: a shell line becomes the commands that really run, with their words, redirections and heredocs; the
wrappers (sudo, env, xargs, sh -c, eval, powershell -Command, cmd /c...) are taken off; a line the reader cannot see
whole says why, and gives no command."""
import unittest

from harness.utils.shell import DEPTH, read
from harness.utils.shell_scan import scan


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


class UnwrapTest(unittest.TestCase):
    def test_wrappers_are_taken_off(self):
        for text in ("sudo rm x", "sudo -n -u root rm x", "env A=1 B=2 rm x", "env -i rm x", "timeout 5 rm x",
                     "timeout -s KILL 5 rm x", "nohup nice -n 5 rm x", "time rm x", "command rm x", "exec rm x",
                     "stdbuf -oL rm x", "builtin rm x"):
            with self.subTest(text=text):
                (command,) = read(text).commands
                self.assertEqual((command.name, [w.text for w in command.args]), ("rm", ["x"]))
                self.assertTrue(command.via)

    def test_xargs_gives_its_command_words_from_stdin(self):
        find, command = read("find . | xargs -0 -n 1 rm -f").commands
        self.assertEqual((find.stdin_args, command.name, command.stdin_args), (False, "rm", True))
        self.assertEqual(read("ls | xargs").commands[-1].name, "echo")

    def test_a_wrapper_option_the_reader_does_not_know_is_unread(self):
        for text in ("sudo --bogus rm x", "timeout --what 5 rm x", "xargs --new rm", "env -S 'rm x'"):
            with self.subTest(text=text):
                self.assertTrue(read(text).unread)

    def test_the_string_a_shell_runs_is_read_again(self):
        line = read("bash -c \"rm x; echo hi > f\"")
        self.assertEqual([c.name for c in line.commands], ["rm", "echo"])
        self.assertEqual([(op, w.text) for op, w in line.commands[1].redirects], [(">", "f")])
        self.assertEqual(names("sh -ec 'rm x' arg0"), (["rm"], []))
        self.assertEqual(names("eval rm x '&&' ls"), (["rm", "ls"], []))
        self.assertEqual(names("bash <<EOF\nrm x\nEOF"), (["rm"], []))

    def test_wrappers_inside_wrappers_are_all_taken_off(self):
        line = read("sudo bash -c \"env A=1 sh -c 'xargs rm'\"")
        self.assertEqual([c.name for c in line.commands], ["rm"])
        self.assertEqual(line.commands[0].via, ("sudo", "bash -c", "env", "sh -c", "xargs"))

    def test_a_wrapper_keeps_its_redirections_on_what_it_runs(self):
        (command,) = read("bash -c 'cat a' > out").commands
        self.assertEqual([(op, w.text) for op, w in command.redirects], [(">", "out")])

    def test_too_deep_or_dynamic_strings_are_unread(self):
        deep = "rm x"
        for _ in range(DEPTH + 1):
            deep = "eval " + "'" + deep.replace("'", "'\\''") + "'"
        for text in (deep, "bash -c \"$CMD\"", "eval $X", "bash -c", "powershell -EncodedCommand AAA"):
            with self.subTest(text=text):
                self.assertTrue(read(text).unread)

    def test_powershell_and_cmd_strings_are_read_in_their_own_dialect(self):
        (command,) = read("powershell -NoProfile -Command \"Remove-Item C:\\a\\b.txt\"").commands
        self.assertEqual((command.name, command.dialect, [w.text for w in command.args]),
                         ("Remove-Item", "powershell", ["C:\\a\\b.txt"]))
        self.assertEqual(names("pwsh -nop -c Get-ChildItem; ls"), (["Get-ChildItem", "ls"], []))
        (command,) = read("cmd /c \"del C:\\x\"").commands
        self.assertEqual((command.name, command.dialect, [w.text for w in command.args]), ("del", "cmd", ["C:\\x"]))


class DialectTest(unittest.TestCase):
    def test_powershell_words(self):
        self.assertEqual(names("Remove-Item C:\\a\\b.txt; Get-ChildItem | Out-File x", "powershell"),
                         (["Remove-Item", "Get-ChildItem", "Out-File"], []))
        self.assertEqual(args("Write-Output 'it''s' \"a\"\"b\"", "powershell"), ["it's", 'a"b'])
        (command,) = read("Set-Content -Path a.txt -Value $v", "powershell").commands
        self.assertEqual([w.dynamic for w in command.args], [False, False, False, True])
        (command,) = read("Get-Content a > b 2>&1 *> c", "powershell").commands
        self.assertEqual([(op, w.text) for op, w in command.redirects], [(">", "b"), (">&", "1"), (">", "c")])

    def test_powershell_that_runs_code_is_unread(self):
        for text in ("Write-Output $(Get-Date)", "Write-Output `n", "& $cmd", "Write-Output @'\nx\n'@",
                     "(Get-Item a).Delete()", "Get-ChildItem | ForEach-Object { Remove-Item $_ }", "x --% y",
                     "Write-Output \"$(rm x)\"", "<# c #> ls"):
            with self.subTest(text=text):
                self.assertTrue(read(text, "powershell").unread)

    def test_cmd_words(self):
        self.assertEqual(names("del a & dir && type b", "cmd"), (["del", "dir", "type"], []))
        self.assertTrue(read("del %X%", "cmd").commands[0].args[0].dynamic)
        for text in ("del ^&x", "(del x)"):
            with self.subTest(text=text):
                self.assertTrue(read(text, "cmd").unread)


if __name__ == "__main__":
    unittest.main()
