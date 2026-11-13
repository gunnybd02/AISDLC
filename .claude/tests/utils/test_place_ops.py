"""h8.edit-gate: a file is edited only under an approved plan and only if the plan names it; the harness's own state is
never edited; the model never fills in the answers of a form."""
import ctypes
import json
import unittest

import harness.gear as gear_block
from harness.assemble.engine.build import build_runner
from harness.assemble.engine.ports import LedgerPort, question
from harness.gear.decide.arbiter import Decide
from harness.gear.detect.forms import Forms
from harness.gear.detect.planfiles import PlanFiles
from harness.gear.detect.tracked import Tracked
from harness.hooks.forms import Answers
from harness.gear.translate.place import Places
from harness.utils.contracts import Event, Finding
from tests import CLAUDE_DIR, tree
from tests.e2e import copy_tree

ROOT = "C:/repo"
PLAN = {"id": 1, "plan_id": "pd-1", "rev": 1, "root": ROOT, "title": "t", "files": ["src/a.py"], "tests": ["test_a.py"]}
STATE = "C:/harness/.claude/state"


def gate(event, facts):
    """The findings of the three detectors of the edit gate, in the order the recipe runs them."""
    return [f for d in (Forms(), Tracked(), PlanFiles()) for f in d.detect(event, facts)]


def write(path, tool="Write", cwd=ROOT):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return Event("PreToolUse", tool, {key: path}, "s1", cwd)


def kinds(event, plan=PLAN, state=STATE):
    facts = {**Places().translate(event), "plan": plan, "state_dir": state}
    return [f.kind for f in gate(event, facts)]


SAID = "Delete the build folder of the project"


def shell(command, tool="Bash", said=SAID, cwd=ROOT, kind="PreToolUse"):
    return Event(kind, tool, {"command": command, "description": said}, "s1", cwd)


def shell_facts(command, **kw):
    return Places().translate(shell(command, **kw))


class ShellPlacesTest(unittest.TestCase):
    """h14.shell-gate: a write through the shell meets the edit gate; a command the reader cannot see whole is asked
    of the user with the agent's own words on what it does; with no such words it is refused."""

    def assert_writes(self, command, paths, tool="Bash", cwd=ROOT):
        facts = shell_facts(command, tool=tool, cwd=cwd)
        self.assertEqual((sorted(facts.get("writes", [])), facts.get("shell_unread")), (sorted(paths), None), command)

    def assert_unread(self, command, tool="Bash"):
        facts = shell_facts(command, tool=tool)
        self.assertTrue(facts.get("shell_unread"), command)
        self.assertEqual((facts["shell_command"], facts["shell_said"]), (command, SAID))

    def test_known_reads_write_nothing(self):
        for command in ("ls -la", "cat a | grep -n x | wc -l", "git status", "git log --oneline -5", "echo hi",
                        "git diff HEAD~1", "find . -name '*.py'", "sed -n 1,5p a.py", "head -3 a && tail b",
                        "env", "git add src/a.py", "git commit -m 'x'", "ls 2>/dev/null", "ls > /dev/null 2>&1",
                        "rg -n pattern src", "python -c 'print(1)'", "pwd; which git"):
            with self.subTest(command=command):
                self.assert_writes(command, [])
        for command in ("Get-ChildItem C:\\repo", "Get-Content a.py | Select-String x", "Test-Path a",
                        "Write-Output hi > $null"):
            with self.subTest(command=command):
                self.assert_writes(command, [], tool="PowerShell")

    def test_writes_are_the_files_the_command_names(self):
        cases = {
            "echo x > src/a.py": ["C:/repo/src/a.py"],
            "cat a >> b 2> err.txt": ["C:/repo/b", "C:/repo/err.txt"],
            "rm -rf build dist": ["C:/repo/build", "C:/repo/dist"],
            "touch -d now a": ["C:/repo/a"],
            "mkdir -p x/y": ["C:/repo/x/y"],
            "cp -r a b": ["C:/repo/b"],
            "mv a b": ["C:/repo/a", "C:/repo/b"],
            "ln -s target link": ["C:/repo/link"],
            "chmod +x run.sh": ["C:/repo/run.sh"],
            "sed -i 's/a/b/' x.py y.py": ["C:/repo/x.py", "C:/repo/y.py"],
            "sed -i.bak -e 's/a/b/' x.py": ["C:/repo/x.py"],
            "tee out.txt": ["C:/repo/out.txt"],
            "curl -sSo page.html https://example.com": ["C:/repo/page.html"],
            "wget -q -O x.zip https://example.com": ["C:/repo/x.zip"],
            "dd if=a of=b": ["C:/repo/b"],
            "cd src && rm a.py": ["C:/repo/a.py", "C:/repo/src/a.py"],
            "cd /c/other && rm z": ["C:/repo/z", "C:/other/z"],
            "sudo rm C:/x/y": ["C:/x/y"],
            "bash -c 'echo hi > f'": ["C:/repo/f"],
            "cat > notes.md <<EOF\nrm -rf /\nEOF": ["C:/repo/notes.md"],
            "echo 'rm -rf / > x'": [],
        }
        for command, paths in cases.items():
            with self.subTest(command=command):
                self.assert_writes(command, paths)
        ps = {
            "Remove-Item C:\\repo\\a.py -Force": ["C:/repo/a.py"],
            "Set-Content -Path a.txt -Value hi": ["C:/repo/a.txt"],
            "Set-Content a.txt hi": ["C:/repo/a.txt"],
            "Out-File -FilePath o.txt -Encoding utf8": ["C:/repo/o.txt"],
            "New-Item -ItemType Directory -Path d": ["C:/repo/d"],
            "Copy-Item a -Destination b": ["C:/repo/b"],
            "Move-Item a b": ["C:/repo/a", "C:/repo/b"],
            "Get-Content a > b": ["C:/repo/b"],
            "rm x": ["C:/repo/x"],
        }
        for command, paths in ps.items():
            with self.subTest(command=command):
                self.assert_writes(command, paths, tool="PowerShell")
        self.assert_writes("cmd /c \"del /q x\"", ["C:/repo/x"])

    def test_a_copy_into_a_folder_writes_the_file_inside_it(self):
        root = tree(self, {"src/keep.txt": "x"})
        cwd = str(root).replace("\\", "/")
        self.assert_writes("cp a.py b.py src", [f"{cwd}/src/a.py", f"{cwd}/src/b.py"], cwd=cwd)
        self.assert_writes("mv a.py src/", [f"{cwd}/a.py", f"{cwd}/src/a.py"], cwd=cwd)

    def test_what_the_reader_cannot_see_whole_is_unread(self):
        for command in ("./build.sh", "make", "npm install", "python setup.py", "py -3.13 -m unittest",
                        "echo $(rm x)", "rm $F", "rm *.py", "echo x > ~/f", "cp a $DEST", "git push",
                        "git checkout -- a.py", "git -c core.pager=x log", "git log --output=f", "find . -delete",
                        "find . -exec rm {} ;", "ls | xargs rm", "tar -xzf a.tgz", "sed 's/a/b/w out' x",
                        "python -c 'open(\"f\", \"w\").write(\"x\")'", "node -e 'require(\"fs\").writeFileSync(a)'",
                        "python - <<EOF\nimport shutil; shutil.rmtree('x')\nEOF", "curl -O https://x/y",
                        "wget https://x/y", "rename a b", "$CMD a", "sudo -u root x", "perl -pi -e 's/a/b/' f"):
            with self.subTest(command=command):
                self.assert_unread(command)
        for command in ("Rename-Item a b", "Remove-Item $p", "Get-ChildItem | ForEach-Object { $_ }",
                        "Invoke-WebRequest -Uri https://x -OutFile y", "Set-Content -Bogus 1 a"):
            with self.subTest(command=command):
                self.assert_unread(command, tool="PowerShell")

    def test_what_once_got_through_unseen_is_unread(self):
        """h16.no-silent-write: each of these deletes a file or runs a program, and was once read as no write."""
        for command in ("python -c \"getattr(__import__('os'),'remove')('x')\"", "python -c 'import os'",
                        "node -p \"process.exit(0)\"", "ruby -e 'Kernel.send(:system, \"x\")'",
                        "rg --pre cat x", "rg --pre=sh x", "sort --compress-program=sh a", "git fetch -u x",
                        "git fetch --upload-pack=x", "git push --receive-pack=x", "git ls-remote -u x"):
            with self.subTest(command=command):
                self.assert_unread(command)
        for command in ("Get-ChildItem *.tmp | Remove-Item -Force", "dir | del", "Get-Item a | Move-Item -Destination d",
                        "Get-ChildItem | Copy-Item -Destination d", "Get-Item a | Clear-Content",
                        "Get-ChildItem | Remove-Item -Recurse"):
            with self.subTest(command=command):
                self.assert_unread(command, tool="PowerShell")
        for command in ("python -c 'print(1)'", "rg -n x src", "sort a", "git fetch origin"):
            with self.subTest(command=command):
                self.assert_writes(command, [])

    def test_only_a_shell_call_before_it_runs_is_read(self):
        self.assertEqual(shell_facts("make", kind="PostToolUse"), {})
        self.assertNotIn("writes", Places().translate(Event("PreToolUse", "Grep", {"command": "make"})))

    def shell_kinds(self, command, said=SAID, plan=PLAN, tool="Bash"):
        event = shell(command, tool=tool, said=said)
        facts = {**Places().translate(event), "plan": plan, "state_dir": STATE}
        return [(f.kind, f.detail) for f in gate(event, facts)]

    def test_a_shell_write_meets_the_edit_gate(self):
        self.assertEqual(self.shell_kinds("echo x > src/a.py"), [])
        self.assertEqual([k for k, _ in self.shell_kinds("echo x > src/b.py")], ["plan.outside"])
        self.assertEqual([k for k, _ in self.shell_kinds("echo x > src/a.py", plan=None)], ["plan.none"])
        self.assertEqual([k for k, _ in self.shell_kinds(f"echo {{}} > {STATE}/pause.json")], ["write.state"])
        self.assertEqual([k for k, _ in self.shell_kinds(f"Set-Content {STATE}/pause.json x", tool="PowerShell")],
                         ["write.state"])

    def test_a_command_the_reader_cannot_see_whole_asks_the_user_with_the_agents_words(self):
        ((kind, detail),) = self.shell_kinds("echo x > src/a.py && ./build.sh --fast")
        self.assertEqual(kind, "shell.unread")
        for part in (SAID, "./build.sh --fast", "C:/repo/src/a.py", "build.sh"):
            self.assertIn(part, detail)

    def test_a_command_the_reader_cannot_see_whole_without_words_of_the_agent_is_refused(self):
        for said in ("", "   ", "make", "./build.sh --fast", "Run it"):
            with self.subTest(said=said):
                self.assertEqual([k for k, _ in self.shell_kinds("./build.sh --fast", said=said)],
                                 ["shell.unexplained"])

    def test_a_refused_write_wins_over_the_question(self):
        kinds_ = [k for k, _ in self.shell_kinds(f"echo x > {STATE}/pause.json; make")]
        self.assertEqual(sorted(kinds_), ["shell.unread", "write.state"])
        self.assertEqual(Decide.load(CLAUDE_DIR).decide([Finding(k) for k in kinds_]).decision, "refuse")


if __name__ == "__main__":
    unittest.main()
