"""h4.doctor (AC5): entry/doctor.py finds no error in the real tree; a broken net or a broken index is an ERROR line
and a non-zero exit."""
import json
import sqlite3
import unittest

from harness.utils.ledger.db import Ledger
from tests import CLAUDE_DIR, tree
from tests.e2e import copy_tree, run

BAD = {
    "imports": {"harness/gear/leak.py": '"""x"""\nimport harness.mcp.hooks\n'},
    "loader": {"harness/gear/__init__.py": "import os\nITEMS = []\n"},
    "config": {"project.json": "{}"},
    "ref": {"harness/gear/__init__.py": '"""x"""\nITEMS = [{"kind": "rule", "name": "decide", '
                                        '"ref": "harness.gear.decide:Typo"}]\n'},
    "skill": {"skills/bad/SKILL.md": "# no frontmatter\n"},
}


class DoctorEntryTest(unittest.TestCase):
    def test_the_real_tree_has_no_error(self):
        code, out, err = run(CLAUDE_DIR / "entry" / "doctor.py")
        self.assertEqual(code, 0, out + err)
        self.assertIn("0 errors", out)

    def test_each_break_is_an_error_and_a_non_zero_exit(self):
        for name, files in BAD.items():
            with self.subTest(name=name):
                code, out, _ = run(copy_tree(self, files) / "entry" / "doctor.py")
                self.assertEqual(code, 1)
                self.assertIn("ERROR", out)

    def test_a_harness_that_exits_quietly_is_still_an_error(self):
        root = copy_tree(self, {"harness/assemble/build.py": "raise SystemExit(0)\n"})
        code, out, _ = run(root / "entry" / "doctor.py")
        self.assertEqual(code, 2)
        self.assertIn("ERROR", out)

    def with_ledger(self, *changes):
        """A tree whose project.json names a ledger in a temp folder, with the schema changes made to it."""
        path = tree(self, {}) / "real.db"
        Ledger.open(path).close()
        con = sqlite3.connect(path)
        for sql in changes:
            con.execute(sql)
        con.commit()
        con.close()
        config = json.loads((CLAUDE_DIR / "project.json").read_text(encoding="utf-8"))
        return copy_tree(self, {"project.json": json.dumps({**config, "ledger": str(path)})})

    def test_the_real_ledger_named_in_the_config_is_compared(self):
        code, out, _ = run(self.with_ledger() / "entry" / "doctor.py")
        self.assertEqual((code, out.strip()), (0, "0 errors"))
        code, out, _ = run(self.with_ledger("ALTER TABLE pl_logs ADD COLUMN extra TEXT") / "entry" / "doctor.py")
        self.assertEqual(code, 1)
        self.assertIn("ERROR ledger", out)
        self.assertIn("table pl_logs", out)

    def test_a_ledger_path_that_is_not_absolute_is_a_config_error(self):
        config = json.loads((CLAUDE_DIR / "project.json").read_text(encoding="utf-8"))
        root = copy_tree(self, {"project.json": json.dumps({**config, "ledger": "state/harness.db"})})
        code, out, _ = run(root / "entry" / "doctor.py")
        self.assertEqual(code, 1)
        self.assertIn("ledger", out)

    def test_the_mcp_server_serves_the_doctor_too(self):
        line = '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"run","arguments":' \
               '{"block":"health","action":"doctor"}}}\n'
        code, out, _ = run(CLAUDE_DIR / "entry" / "mcp_server.py", line)
        self.assertEqual(code, 0)
        self.assertIn("0 errors", out)


if __name__ == "__main__":
    unittest.main()
