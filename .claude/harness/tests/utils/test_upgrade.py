"""The ledger's schema version and its one upgrade door (docs/12-ledger.md): an older ledger becomes the latest in one
transaction with every row kept; a fault changes nothing; only the code in force upgrades, any other writer refuses."""
import sqlite3
import unittest
from unittest import mock

from harness.assemble.engine import ledger_core
from harness.utils.gateway.release import build, publish, release_dir
from harness.utils.ledger import db
from harness.utils.ledger.db import Ledger, LedgerError
from harness.utils.ledger.upgrade import upgrade
from harness.tests import tree


def old_ledger(test, version=1, user_version=0):
    """A ledger file with exactly an older version's structure and one row in sessions and in pl_logs."""
    path = tree(test, {}) / "state" / "harness.db"
    path.parent.mkdir()
    con = sqlite3.connect(path, isolation_level=None)
    for sql in db.statements(version):
        con.execute(sql)
    con.execute(f"PRAGMA user_version = {user_version}")
    con.execute("INSERT INTO sessions (sid, started_at, last_at) VALUES ('s1', 1, 2)")
    con.execute("INSERT INTO pl_logs (uid, body, at) VALUES ('u1', '{}', 3)")
    con.close()
    return path


class UpgradeTest(unittest.TestCase):
    def test_an_older_ledger_becomes_the_latest_with_every_row_in_place(self):
        path = old_ledger(self)
        con = sqlite3.connect(path, isolation_level=None)
        self.addCleanup(con.close)
        self.assertEqual(db.version_of(con), 1)
        self.assertEqual(upgrade(con), (1, db.latest()))
        self.assertEqual(db.fingerprint(con), db.pinned())
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], db.latest())
        self.assertEqual(con.execute("SELECT sid, last_at FROM sessions").fetchall(), [("s1", 2)])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM pl_maint_runs").fetchone()[0], 0)  # a table of version 2
        logs = [r[0] for r in con.execute("SELECT body FROM pl_logs ORDER BY at")]
        self.assertEqual(logs[0], "{}")
        self.assertIn('"what": "ledger-upgrade"', logs[1])
        self.assertEqual(upgrade(con), (db.latest(), db.latest()))  # once: a second opener finds the latest
        copy = sqlite3.connect(":memory:")
        self.addCleanup(copy.close)
        con.backup(copy)
        self.assertEqual(copy.execute("PRAGMA user_version").fetchone()[0], db.latest())  # a copy carries its version

    def test_a_fault_rolls_all_of_it_back(self):
        path = old_ledger(self)
        con = sqlite3.connect(path, isolation_level=None)
        self.addCleanup(con.close)
        broken = {**db.blocks(), db.latest(): db.blocks()[db.latest()] + ["CREATE TABLE sessions (x)"]}
        with mock.patch.object(db, "blocks", lambda: broken), mock.patch("harness.utils.ledger.upgrade.blocks", lambda: broken):
            with self.assertRaises(sqlite3.Error):
                upgrade(con)
        self.assertFalse(con.in_transaction)
        self.assertEqual(db.fingerprint(con), db.pinned(1))  # the structure it had
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM pl_logs").fetchone()[0], 1)
        drifted = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(drifted.close)
        drifted.execute("CREATE TABLE other (x)")
        with self.assertRaisesRegex(LedgerError, "no schema version"):
            upgrade(drifted)

    def test_a_writer_refuses_another_version_and_only_the_code_in_force_upgrades(self):
        path = old_ledger(self)
        with self.assertRaisesRegex(LedgerError, "schema mismatch: the ledger is version 1 .* reads version"):
            Ledger.open(path)
        self.assertEqual(db.query(path, "SELECT sid FROM sessions")[1], [("s1",)])  # a read-only open still reads it
        opened = Ledger.open(path, upgrade=True)  # the one door
        self.addCleanup(opened.close)
        self.assertEqual(db.version_of(opened.con), db.latest())
        self.assertEqual(opened.one("SELECT sid FROM sessions")["sid"], "s1")
        newer = old_ledger(self, version=db.latest(), user_version=db.latest() + 1)
        con = sqlite3.connect(newer, isolation_level=None)
        con.execute("CREATE TABLE later (x)")
        con.close()
        with self.assertRaisesRegex(LedgerError, "newer than this code"):
            Ledger.open(newer, upgrade=True)
        other = tree(self, {}) / "harness.db"
        con = sqlite3.connect(other)
        con.execute("CREATE TABLE other (x)")
        con.commit()
        con.close()
        with self.assertRaisesRegex(LedgerError, "drifted"):
            Ledger.open(other, upgrade=True)

    def test_the_code_in_force_is_the_release_published_or_the_work_tree_when_none_is(self):
        home = tree(self, {"harness/a.py": "A = 1\n"})
        here = ledger_core.Path(ledger_core.__file__).resolve().parents[3]
        self.assertFalse(ledger_core.in_force(home))  # another home's ledger is never this code's to upgrade
        self.assertTrue(ledger_core.in_force(here) or ledger_core.current(here) is not None)
        sha = build(home)
        publish(home, sha)
        with mock.patch.object(ledger_core, "__file__", str(release_dir(home, sha) / "harness" / "assemble" / "engine" / "ledger_core.py")):
            self.assertTrue(ledger_core.in_force(home))  # the published release
        with mock.patch.object(ledger_core, "__file__", str(home / "harness" / "assemble" / "engine" / "ledger_core.py")):
            self.assertFalse(ledger_core.in_force(home))  # its work tree, once a release is published
        fresh = tree(self, {}) / "state" / "harness.db"
        opened = Ledger.open(fresh)
        self.addCleanup(opened.close)
        self.assertEqual(opened.con.execute("PRAGMA user_version").fetchone()[0], db.latest())  # a new ledger is the latest


if __name__ == "__main__":
    unittest.main()
