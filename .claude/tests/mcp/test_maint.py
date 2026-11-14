"""h10.maint-grant: the maint block gives the form question to ask, and says whether the guards are off."""
import json
import time
import unittest

from harness.assemble.engine.ports import LedgerPort
from tests import tree
from tests.mcp import caller

Q = "T\u1eaft guard 15 ph\u00fat: s\u1eeda harness?"


class MaintBlockTest(unittest.TestCase):
    def setUp(self):
        self.root = tree(self, {})
        self.run = caller(self.root)

    def test_grant_gives_the_question_to_ask(self):
        self.assertIn(Q, self.run("maint", "grant", minutes=15, why="s\u1eeda harness").text)
        for minutes in (0, 121, True, 1.5):
            with self.subTest(minutes=minutes):
                self.assertTrue(self.run("maint", "grant", minutes=minutes, why="x").is_error)

    def test_status_reads_the_grant_of_the_ledger(self):
        def status():
            return self.run("maint", "status").text
        self.assertEqual(status(), "The guards are on.")
        LedgerPort(self.root).write(lambda con, rec: con.execute(
            "INSERT INTO pl_notes (uid, kind, text, why, at) VALUES ('u', 'maint.grant', ?, 'fix', 1)",
            (json.dumps({"until": time.time() + 600}),)))
        self.assertIn("off for 9 more minutes: fix", status())


if __name__ == "__main__":
    unittest.main()
