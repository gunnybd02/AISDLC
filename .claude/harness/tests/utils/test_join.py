"""Part 7, the join (utils/ledger/join.py): ledger copies, gzipped as the store holds them, merge into one memory beside
the ledger, each row once by its uid or key; a copy of another schema is refused; db_query with memory true reads it."""
import sqlite3
import unittest

from harness.mcp.actions.ledger import DbQuery, Join
from harness.utils.contracts import ActionContext, ActionError
from harness.utils.ledger.db import Ledger
from harness.utils.ledger.export import snapshot
from harness.utils.ledger.join import COPIES, memory_of
from harness.tests import tree


class Port:
    """The ledger port as the actions read it: its path."""

    def __init__(self, path):
        self.path = path


class JoinTest(unittest.TestCase):
    def setUp(self):
        self.root = tree(self, {})
        self.ledger = self.root / "state" / "harness.db"
        self.ledger.parent.mkdir()
        Ledger.open(self.ledger).close()
        self.ctx = ActionContext({"ledger": Port(self.ledger)})

    def copy_of(self, name, rows):
        """A real ledger of a session with these pl_logs rows, exported as the store holds it (.db.gz)."""
        db = self.root / name / "harness.db"
        db.parent.mkdir()
        ledger = Ledger.open(db)
        ledger.write(lambda con: con.executemany("INSERT INTO pl_logs (uid, body, at) VALUES (?, ?, 1)", rows))
        ledger.write(lambda con: con.execute("INSERT INTO pl_asks (sid, key, at, used) VALUES (?, 'k', 1, 0)", (name,)))
        ledger.close()
        return snapshot(db, self.root / "out" / name, {"title": f"{name}__x-001__t__stop__c__s1.db", "session": name})["path"]

    def test_copies_merge_into_one_memory_each_row_once(self):
        """s7.join.copies"""
        parent = self.copy_of("parent", [("u1", "plan"), ("u2", "form 1")])
        child = self.copy_of("child", [("u2", "form 1"), ("u3", "handback")])  # u2 in both copies
        text = Join().run(self.ctx, {"files": [parent, child]})
        self.assertEqual(text.splitlines()[0], f"{parent.rsplit('/', 1)[1]}: 3 rows taken")
        self.assertIn("2 rows taken", text.splitlines()[1])  # u3 and its own pl_asks row; u2 once
        self.assertIn("joined already", Join().run(self.ctx, {"files": [child]}))
        memory = sqlite3.connect(memory_of(self.ledger))
        try:
            self.assertEqual([r[0] for r in memory.execute("SELECT uid FROM pl_logs ORDER BY uid")], ["u1", "u2", "u3"])
            self.assertEqual(memory.execute(f"SELECT count(*) FROM {COPIES}").fetchone()[0], 2)
        finally:
            memory.close()
        live = sqlite3.connect(self.ledger)
        try:
            self.assertEqual(live.execute("SELECT count(*) FROM pl_logs").fetchone()[0], 0)  # the ledger is untouched
        finally:
            live.close()
        odd = self.root / "odd.db"
        con = sqlite3.connect(odd)
        con.execute("CREATE TABLE t (x)")
        con.close()
        self.assertIn("refused, its schema is not the harness's", Join().run(self.ctx, {"files": [str(odd)]}))
        self.assertIn("no such file", Join().run(self.ctx, {"files": [str(self.root / "none.db.gz")]}))
        with self.assertRaises(ActionError):
            Join().run(self.ctx, {"files": []})

    def test_db_query_with_memory_reads_the_joined_memory(self):
        """s7.join.query"""
        with self.assertRaisesRegex(ActionError, "there is no memory yet"):
            DbQuery().run(self.ctx, {"sql": "SELECT 1", "memory": True})
        Join().run(self.ctx, {"files": [self.copy_of("child", [("u3", "handback")])]})
        self.assertEqual(DbQuery().run(self.ctx, {"sql": "SELECT body FROM pl_logs", "memory": True}), "body\nhandback")
        self.assertEqual(DbQuery().run(self.ctx, {"sql": "SELECT count(*) AS n FROM pl_logs"}), "n\n0")
        with self.assertRaisesRegex(ActionError, "refused or wrong"):
            DbQuery().run(self.ctx, {"sql": "DELETE FROM pl_logs", "memory": True})


if __name__ == "__main__":
    unittest.main()
