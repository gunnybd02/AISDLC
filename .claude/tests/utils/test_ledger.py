"""h6.ledger: the private DB has the real ledger's schema, pinned by its fingerprint, and every write is whole or
nothing; chained rows carry the hash of the row before them."""
import sqlite3
import unittest

from harness.utils.ledger.db import SCHEMA, Ledger, LedgerError, fingerprint, normal
from harness.utils.ledger.recorder import Recorder
from tests import tree

TABLES = ("sessions", "rec_plans", "rec_commits", "pl_plan_revs", "pl_plan_events", "pl_verify", "act_rule_decisions",
          "pl_logs", "rec_edits")


class LedgerTest(unittest.TestCase):
    def ledger(self):
        return Ledger.open(tree(self, {}) / "state" / "harness.db")

    def test_a_new_db_has_the_schema_of_the_real_ledger(self):
        names = {r["name"] for r in self.ledger().all("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
        self.assertLessEqual(set(TABLES) | {"pl_retro_plan", "pl_plan_facts"}, names)

    def test_the_schema_copy_is_whole(self):
        text = SCHEMA.read_text(encoding="utf-8")
        self.assertEqual(text.count("CREATE TABLE"), 40)
        self.assertEqual(text.count("CREATE INDEX"), 19)
        self.assertEqual(text.count("CREATE VIEW"), 4)

    def test_a_db_whose_schema_drifted_does_not_open(self):
        root = tree(self, {})
        path = root / "harness.db"
        Ledger.open(path).close()
        con = sqlite3.connect(path)
        con.execute("ALTER TABLE pl_logs ADD COLUMN extra TEXT")
        con.commit()
        con.close()
        with self.assertRaises(LedgerError):
            Ledger.open(path)

    def test_the_fingerprint_ignores_spaces_and_comments_only(self):
        self.assertEqual(normal("CREATE  TABLE a (x TEXT) -- note\n"), normal("CREATE TABLE a (x TEXT)"))
        self.assertNotEqual(normal("CREATE TABLE a (x TEXT)"), normal("CREATE TABLE a (x INTEGER)"))
        con = sqlite3.connect(":memory:")
        con.executescript("CREATE TABLE a (x TEXT);")
        before = fingerprint(con)
        con.executescript("CREATE TRIGGER t AFTER INSERT ON a BEGIN SELECT 1; END;")
        self.assertNotEqual(before, fingerprint(con))

    def test_a_write_that_fails_leaves_nothing(self):
        ledger = self.ledger()
        rec = Recorder(ledger)

        def half(con):
            rec.insert(con, "pl_logs", {"uid": "a", "body": "x", "at": 1})
            raise RuntimeError("stop")

        with self.assertRaises(RuntimeError):
            ledger.write(half)
        self.assertEqual(ledger.all("SELECT * FROM pl_logs"), [])

    def test_chained_rows_carry_the_hash_of_the_row_before(self):
        ledger = self.ledger()
        rec = Recorder(ledger)
        for n in (1, 2):
            ledger.write(lambda con, n=n: rec.insert(con, "rec_commits", {
                "plan_id": 1, "service": "u", "commit_sha": f"s{n}", "at": n, "uid": f"u{n}"}))
        first, second = ledger.all("SELECT prev_hash, hash FROM rec_commits ORDER BY at")
        self.assertEqual((first["prev_hash"], second["prev_hash"]), ("", first["hash"]))
        self.assertTrue(Recorder.chain_ok(ledger, "rec_commits"))
        con = sqlite3.connect(ledger.path)
        con.execute("UPDATE rec_commits SET commit_sha = 'forged' WHERE at = 1")
        con.commit()
        con.close()
        self.assertFalse(Recorder.chain_ok(Ledger.open(ledger.path), "rec_commits"))

    def test_an_unknown_table_or_column_is_refused(self):
        ledger = self.ledger()
        rec = Recorder(ledger)
        for table, row in (("nope", {"a": 1}), ("pl_logs", {"nope": 1})):
            with self.subTest(table=table), self.assertRaises(LedgerError):
                ledger.write(lambda con: rec.insert(con, table, row))


if __name__ == "__main__":
    unittest.main()
