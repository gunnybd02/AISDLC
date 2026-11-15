"""h11.one-store: the ledger is read only through db_query, one read-only SELECT that never reads transcripts."""
import os
import sqlite3
import unittest
from unittest import mock

from harness.assemble.engine.ports import LedgerPort
from harness.utils.ledger.db import LedgerError, query
from harness.tests import tree
from harness.tests.e2e import copy_tree
from harness.tests.mcp import caller


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


class ExportActionTest(unittest.TestCase):
    """h23.store: export answers the Drive call of a copy; with no store folder it is refused and copies nothing."""

    def setUp(self):
        self.root = copy_tree(self)  # a write action meets the real judge
        self.port = LedgerPort(self.root)
        self.port.write(lambda con, rec: con.execute("INSERT INTO pl_logs (uid, body, at) VALUES ('u', 'b', 1)"))
        self.port.touch_session("s-export-test")
        self.run_action = caller(self.root)
        self.temp = tree(self, {})
        patch = mock.patch("tempfile.gettempdir", return_value=str(self.temp))
        patch.start()
        self.addCleanup(patch.stop)

    def export(self, folder_env="", **args):
        with mock.patch.dict(os.environ, {"HARNESS_DRIVE_FOLDER": folder_env}):
            return self.run_action("ledger", "export", **args)

    def test_with_no_store_folder_nothing_is_copied(self):
        for result in (self.export(), self.export(folder="no")):
            self.assertTrue(result.is_error)
            self.assertIn("HARNESS_DRIVE_FOLDER", result.text)
        self.assertFalse((self.temp / "harness-export").exists())

    def test_the_answer_is_the_drive_call_of_a_copy_with_the_ledgers_rows(self):
        for result, folder in ((self.export("folder-from-env-1"), "folder-from-env-1"),
                               (self.export("folder-from-env-1", folder="folder-given-22"), "folder-given-22")):
            self.assertFalse(result.is_error, result.text)
            self.assertIn(f"  parentId: {folder}", result.text.splitlines())
            self.assertIn("create_file", result.text)
        (copy,) = (self.temp / "harness-export").glob("s-export-test__*.db")  # one copy a session
        self.assertIn(f"base64Content: sha256:", result.text)
        self.assertIn(copy.resolve().as_posix(), result.text)
        con = sqlite3.connect(copy)
        self.assertEqual(con.execute("SELECT uid FROM pl_logs").fetchall(), [("u",)])
        con.close()

    def test_a_commits_answer_says_the_copy_is_due_only_with_a_store(self):
        from harness.mcp.actions.ledger import STORE_NOTE, store_note
        from harness.utils.contracts import ActionContext
        self.assertEqual(store_note(ActionContext({"store": lambda: ""})), "")
        self.assertEqual(store_note(ActionContext({"store": lambda: "folder-id-123"})), STORE_NOTE)
        self.assertIn("run('ledger', 'export', {})", STORE_NOTE)


if __name__ == "__main__":
    unittest.main()
