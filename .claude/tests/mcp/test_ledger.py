"""h11.one-store: the ledger is read only through db_query, one read-only SELECT that never reads transcripts."""
import sqlite3
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.utils.ledger.db import LedgerError, query
from tests import tree
from tests.mcp import caller


class DbQueryTest(unittest.TestCase):
    def setUp(self):
        self.root = tree(self, {})
        self.port = LedgerPort(self.root)
        self.port.write(lambda con, rec: con.execute("INSERT INTO pl_logs (uid, body, at) VALUES ('u', 'b', 1)"))
        run = caller(self.root)

        def db_query(sql):
            result = run("ledger", "db_query", sql=sql)
            if result.is_error:
                raise LedgerError(result.text)
            return result.text
        self.db_query = db_query

    def test_a_select_answers_its_rows(self):
        self.assertEqual(self.db_query(sql="SELECT uid, body FROM pl_logs"), "uid\tbody\nu\tb")

    def test_anything_but_one_read_is_refused_and_changes_nothing(self):
        for sql in ("DELETE FROM pl_logs", "UPDATE pl_logs SET body = 'x'", "INSERT INTO pl_logs (uid) VALUES ('v')",
                    "DROP TABLE pl_logs", "PRAGMA table_info(pl_logs)", "ATTACH 'x.db' AS x",
                    "SELECT 1; DELETE FROM pl_logs", "CREATE TABLE t (a)"):
            with self.subTest(sql=sql), self.assertRaises(LedgerError):
                self.db_query(sql=sql)
        self.assertEqual(self.db_query(sql="SELECT count(*) FROM pl_logs"), "count(*)\n1")

    def test_the_transcript_tables_are_never_read(self):
        path = self.root / "t.db"
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE tx_messages (text)")
        con.execute("INSERT INTO tx_messages VALUES ('secret')")
        con.commit()
        con.close()
        for sql in ("SELECT * FROM tx_messages", "SELECT * FROM TX_MESSAGES", "SELECT (SELECT text FROM tx_messages)"):
            with self.subTest(sql=sql), self.assertRaises(LedgerError):
                query(path, sql)

    def test_a_long_answer_is_cut(self):
        columns, rows, cut = query(self.port.path, "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n "
                                                   "WHERE i < 500) SELECT i FROM n")
        self.assertEqual((len(rows), cut), (200, True))


if __name__ == "__main__":
    unittest.main()
