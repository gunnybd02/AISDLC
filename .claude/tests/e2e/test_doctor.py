"""h4.doctor (AC5): entry/doctor.py finds no error in the real tree; a broken net or a broken index is an ERROR line
and a non-zero exit."""
import unittest

from tests import CLAUDE_DIR
from tests.e2e import copy_tree, run

BAD = {
    "imports": {"harness/gear/leak.py": '"""x"""\nimport harness.mcp.hooks\n'},
    "loader": {"harness/gear/__init__.py": "import os\nITEMS = []\n"},
    "config": {"project.json": "{}"},
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

    def test_the_mcp_server_serves_the_doctor_too(self):
        line = '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"run","arguments":' \
               '{"block":"health","action":"doctor"}}}\n'
        code, out, _ = run(CLAUDE_DIR / "entry" / "mcp_server.py", line)
        self.assertEqual(code, 0)
        self.assertIn("0 errors", out)


if __name__ == "__main__":
    unittest.main()
