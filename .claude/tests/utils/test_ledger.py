"""h6.ledger: the private DB has the real ledger's schema, pinned by its fingerprint, and every write is whole or
nothing; chained rows carry the hash of the row before them."""
import sqlite3
import unittest
from unittest import mock

from harness.utils.ledger import db
from harness.utils.ledger.db import SCHEMA, Ledger, LedgerError, compare_real, fingerprint, normal, statements
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

    def test_the_id_of_a_plan_row_is_in_its_hash(self):
        ledger = self.ledger()
        rec = Recorder(ledger)
        rid = ledger.write(lambda con: rec.insert(con, "rec_plans", {"sid": "s", "status": "approved", "at": 1}))
        self.assertTrue(Recorder.chain_ok(ledger, "rec_plans"))
        con = sqlite3.connect(ledger.path)
        con.execute("UPDATE rec_plans SET id = ? WHERE id = ?", (rid + 5, rid))
        con.commit()
        con.close()
        self.assertFalse(Recorder.chain_ok(Ledger.open(ledger.path), "rec_plans"))

    def test_an_empty_file_left_by_a_crash_gets_the_schema(self):
        path = tree(self, {"harness.db": ""}) / "harness.db"
        ledger = Ledger.open(path)
        self.assertIsNotNone(ledger.one("SELECT name FROM sqlite_master WHERE name = 'rec_plans'"))

    def test_an_unknown_table_or_column_is_refused(self):
        ledger = self.ledger()
        rec = Recorder(ledger)
        for table, row in (("nope", {"a": 1}), ("pl_logs", {"nope": 1})):
            with self.subTest(table=table), self.assertRaises(LedgerError):
                ledger.write(lambda con: rec.insert(con, table, row))


def snapshot(folder):
    """{name: bytes} of every file in folder: what a read-only check must leave as it was."""
    return {p.name: p.read_bytes() for p in folder.iterdir()}


class RealLedgerTest(unittest.TestCase):
    """h12.real-ledger: the doctor opens the real ledger read only and names every object whose schema drifted from
    schema.sql; a ledger it cannot read is a problem, never a match; it never writes a byte or makes a file."""

    def real(self, *changes, wal=False):
        root = tree(self, {})
        path = root / "harness.db"
        Ledger.open(path).close()
        con = sqlite3.connect(path)
        if wal:
            con.execute("PRAGMA journal_mode=WAL")
        for sql in changes:
            con.execute(sql)
        con.commit()
        con.close()
        return path

    def test_a_ledger_with_the_same_schema_has_no_problem_and_is_left_as_it_was(self):
        path = self.real()
        before = snapshot(path.parent)
        self.assertEqual(compare_real(path), [])
        self.assertEqual(snapshot(path.parent), before)

    def test_each_drifted_object_is_named(self):
        view = next(s for s in statements() if s.startswith("CREATE VIEW pl_retro_rule"))
        index = next(s for s in statements() if s.startswith("CREATE INDEX")).split()[2]
        path = self.real("ALTER TABLE pl_logs ADD COLUMN extra TEXT",
                         "DROP VIEW pl_retro_rule", view.replace("SELECT", "SELECT 1 AS one,", 1),
                         f"DROP INDEX {index}",
                         "CREATE TRIGGER stray AFTER INSERT ON pl_logs BEGIN SELECT 1; END")
        before = snapshot(path.parent)
        problems = compare_real(path)
        text = "\n".join(problems)
        for word in ("table pl_logs", "view pl_retro_rule", "trigger stray", "index "):
            self.assertIn(word, text)
        self.assertEqual(len(problems), 4, text)
        self.assertEqual(snapshot(path.parent), before)

    def test_a_ledger_that_cannot_be_read_is_a_problem_not_a_match(self):
        root = tree(self, {"broken.db": "not a database at all, just text" * 20})
        for path in (root / "missing.db", root / "broken.db"):
            with self.subTest(path=path.name):
                before = snapshot(root)
                problems = compare_real(path)
                self.assertEqual(len(problems), 1)
                self.assertIn("not compared", problems[0])
                self.assertEqual(snapshot(root), before)

    def test_an_empty_file_is_not_compared(self):
        path = tree(self, {"real.db": ""}) / "real.db"
        self.assertEqual(compare_real(path), [f"{path}: an empty file; its schema is not compared"])

    def test_a_writer_that_shows_up_during_the_read_voids_it(self):
        path = self.real()
        real = db.objects

        def read_while_a_writer_starts(con):
            path.with_name(path.name + "-journal").write_bytes(b"")
            return real(con)

        with mock.patch.object(db, "objects", read_while_a_writer_starts):
            problems = compare_real(path)
        self.assertEqual(problems, [f"{path}: it was written to while being read; its schema is not compared"])

    def test_a_wal_without_its_shm_is_not_opened(self):
        path = self.real(wal=True)
        path.with_name(path.name + "-wal").write_bytes(b"")
        before = snapshot(path.parent)
        problems = compare_real(path)
        self.assertEqual(len(problems), 1)
        self.assertIn("-shm", problems[0])
        self.assertEqual(snapshot(path.parent), before)

    def test_a_wal_ledger_at_rest_is_read_and_no_file_is_made(self):
        path = self.real(wal=True)
        before = snapshot(path.parent)
        self.assertEqual(compare_real(path), [])
        self.assertEqual(snapshot(path.parent), before)

    def test_a_ledger_in_use_is_read_through_its_wal_and_only_the_shm_may_change(self):
        path = self.real(wal=True)
        writer = sqlite3.connect(path)
        self.addCleanup(writer.close)
        writer.execute("CREATE TRIGGER stray AFTER INSERT ON pl_logs BEGIN SELECT 1; END")
        writer.commit()
        before = {k: v for k, v in snapshot(path.parent).items() if not k.endswith("-shm")}
        self.assertIn("harness.db-wal", before)
        self.assertEqual(compare_real(path), [f"{path}: trigger stray is not in schema.sql"])
        self.assertEqual({k: v for k, v in snapshot(path.parent).items() if not k.endswith("-shm")}, before)

if __name__ == "__main__":
    unittest.main()
