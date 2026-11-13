"""h10.maint-grant: the maint block gives the form question to ask, and says whether the guards are off."""
import json
import time
import unittest

from harness.assemble.engine.build import items_of
from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.wire_mcp import action_table
from tests import CLAUDE_DIR, tree

Q = "T\u1eaft guard 15 ph\u00fat: s\u1eeda harness?"


class MaintBlockTest(unittest.TestCase):
    def setUp(self):
        self.root = tree(self, {})
        self.table = action_table(items_of(CLAUDE_DIR), self.root)

    def test_grant_gives_the_question_to_ask(self):
        self.assertIn(Q, self.table.action("maint", "grant").handler(minutes=15, why="s\u1eeda harness"))
        for minutes in (0, 121, True):
            with self.subTest(minutes=minutes), self.assertRaises(ValueError):
                self.table.action("maint", "grant").handler(minutes=minutes, why="x")

    def test_status_reads_the_grant_of_the_ledger(self):
        status = self.table.action("maint", "status").handler
        self.assertEqual(status(), "The guards are on.")
        LedgerPort(self.root).write(lambda con, rec: con.execute(
            "INSERT INTO pl_notes (uid, kind, text, why, at) VALUES ('u', 'maint.grant', ?, 'fix', 1)",
            (json.dumps({"until": time.time() + 600}),)))
        self.assertIn("off for 9 more minutes: fix", status())


if __name__ == "__main__":
    unittest.main()
