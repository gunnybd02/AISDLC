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
