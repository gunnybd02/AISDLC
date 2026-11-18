"""What a session wrote and ran is recorded by the harness (docs/12-ledger.md): each file with the hash of its
content, counted; each shell line with a start row and an end row, secrets masked."""
import subprocess
import unittest

from harness.assemble.engine.build import build_runner
from harness.assemble.engine.ports import LedgerPort
from harness.utils.contracts import Event
from harness.utils.ledger import writes
from harness.utils.shell.after import top_of
from harness.tests.e2e import copy_tree, git_repo

KEY = "ghp_" + "a1B2c3D4" * 5  # the shape of a token, not one


class WritesTest(unittest.TestCase):
    def setUp(self):
        self.claude_dir = copy_tree(self)
        self.repo = git_repo(self, {"a.py": "X = 1\n"})
        self.port = LedgerPort(self.claude_dir)

    def hook(self, kind, tool, tool_input, response=None):
        return build_runner(self.claude_dir).run(Event(kind, tool, tool_input, "s1", str(self.repo), response))

    def rows(self, sql):
        return [tuple(r[k] for k in r.keys()) for r in self.port.rows(sql)]

    def test_a_file_write_is_kept_with_its_content_hash_and_counted(self):
        a = self.repo / "a.py"
        git_id = subprocess.run(["git", "-C", str(self.repo), "hash-object", "a.py"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(writes.content_hash(str(a)), git_id)  # the id git gives the content
        self.assertEqual(writes.content_hash(str(self.repo / "nothere.py")), "")
        for _ in range(2):
            self.hook("PostToolUse", "Write", {"file_path": str(a), "content": "X = 1\n"})
        a.write_text("X = 2\n", encoding="utf-8")
        self.hook("PostToolUse", "Edit", {"file_path": str(a), "old_string": "1", "new_string": "2"})
        self.hook("PreToolUse", "Write", {"file_path": str(a), "content": "X = 3\n"})  # before it runs: nothing written yet
        real = writes.real(str(a))
        rows = self.rows("SELECT service, edits, plan_id FROM rec_edits WHERE sid = 's1' ORDER BY first_at, rowid")
        self.assertEqual(rows, [(f"wrote:{git_id}:{real}", 2, 0), (f"wrote:{writes.content_hash(str(a))}:{real}", 1, 0)])
        self.assertEqual(self.port.written("s1"), {real: {git_id, writes.content_hash(str(a))}})
        self.assertEqual(self.port.written("other"), {})

    def test_a_shell_line_has_a_start_row_and_an_end_row_and_its_writes_are_kept(self):
        line = f"echo {KEY} > out.txt"
        self.hook("PreToolUse", "Bash", {"command": line})
        (self.repo / "out.txt").write_text("x\n", encoding="utf-8")
        self.hook("PostToolUse", "Bash", {"command": line}, {"stdout": "", "stderr": "", "interrupted": False})
        self.hook("PreToolUse", "Bash", {"command": "sleep 100"})  # never reports: its start row stays
        self.hook("PostToolUse", "Bash", {"command": "false"}, {"exit_code": 1})
        self.hook("PostToolUse", "Bash", {"command": "sleep 9"}, {"interrupted": True})
        rows = self.rows("SELECT door, command, output, exit, sid FROM pl_maint_runs ORDER BY rowid")
        self.assertEqual(rows, [("shell", "[redacted]", "start", -1, "s1"), ("shell", "[redacted]", "ok", -1, "s1"),
                                ("shell", "sleep 100", "start", -1, "s1"), ("shell", "false", "failed", 1, "s1"),
                                ("shell", "sleep 9", "interrupted", -1, "s1")])
        self.assertNotIn(KEY, str(self.rows("SELECT command, cwd, output FROM pl_maint_runs")))
        self.assertIn(writes.real(str(self.repo / "out.txt")), self.port.written("s1"))  # the line's target, read
        self.assertEqual(len(self.rows("SELECT command FROM pl_maint_runs WHERE command = 'sleep 100'")), 1)

    def test_an_unclear_line_in_auto_mode_keeps_its_repository_before_it_runs(self):
        """s4.auto.snapshot: the snapshot is kept under the call id; in another mode none is kept."""
        (self.repo / "a.py").write_text("X = 2\n", encoding="utf-8")
        said = "Build the project with make"
        auto = Event("PreToolUse", "Bash", {"command": "make", "description": said}, "s1", str(self.repo), None, "auto",
                     "toolu_1")
        self.assertEqual(build_runner(self.claude_dir).run(auto).verdict.decision, "allow")
        top = top_of(str(self.repo))
        self.assertEqual(self.port.read(lambda con: writes.before_of(con, "toolu_1")),
                         {top: {"a.py": writes.content_hash(str(self.repo / "a.py"))}})
        asked = Event("PreToolUse", "Bash", {"command": "make", "description": said}, "s1", str(self.repo), None,
                      "default", "toolu_2")
        self.assertEqual(build_runner(self.claude_dir).run(asked).verdict.decision, "ask")
        self.assertIsNone(self.port.read(lambda con: writes.before_of(con, "toolu_2")))
        self.assertIsNone(self.port.read(lambda con: writes.before_of(con, "")))

    def test_the_files_an_unclear_line_changed_are_kept_as_its_writes(self):
        """s5.after.recorded: after the line ran, each file it changed is a write of the session, with its content."""
        call = {"command": "make", "description": "Build the project with make"}
        build_runner(self.claude_dir).run(Event("PreToolUse", "Bash", call, "s1", str(self.repo), None, "auto", "t1"))
        (self.repo / "a.py").write_text("X = 5\n", encoding="utf-8")
        (self.repo / "made.txt").write_text("m\n", encoding="utf-8")
        outcome = build_runner(self.claude_dir).run(Event("PostToolUse", "Bash", call, "s1", str(self.repo),
                                                          {"exit_code": 0}, "auto", "t1"))
        self.assertEqual(outcome.verdict.decision, "refuse")  # no plan names them: the agent is told
        self.assertIn("made.txt", outcome.verdict.reason)
        written = self.port.written("s1")
        for name in ("a.py", "made.txt"):
            real = writes.real(str(self.repo / name))
            self.assertEqual(written[real], {writes.content_hash(real)})

    def test_how_a_shell_line_ended_is_read_from_the_tools_answer(self):
        self.assertEqual(writes.outcome({"exit_code": 0}), ("ok", 0))
        self.assertEqual(writes.outcome({"returncode": 3}), ("failed", 3))
        self.assertEqual(writes.outcome({"is_error": True}), ("failed", -1))
        self.assertEqual(writes.outcome({"interrupted": True, "exit_code": 0}), ("interrupted", -1))
        self.assertEqual(writes.outcome("text"), ("ok", -1))
        long = "echo " + "y" * 5000
        self.hook("PreToolUse", "Bash", {"command": long})
        self.assertEqual(self.rows("SELECT length(command) FROM pl_maint_runs"), [(writes.SHELL_MOST,)])


if __name__ == "__main__":
    unittest.main()
