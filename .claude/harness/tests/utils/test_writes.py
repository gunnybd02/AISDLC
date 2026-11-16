"""What a session wrote and ran is recorded by the harness (docs/12-ledger.md): each file with the hash of its
content, counted; each shell line with a start row and an end row, secrets masked."""
import subprocess
import unittest

from harness.assemble.engine.build import build_runner
from harness.assemble.engine.ports import LedgerPort
from harness.utils.contracts import Event
from harness.utils.ledger import writes
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
