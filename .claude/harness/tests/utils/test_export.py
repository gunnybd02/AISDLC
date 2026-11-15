"""h23.store: a ledger's copy for the store outside the machine is whole, has the pinned schema, and is named by
session, time, commit and schema; a ledger whose schema drifted is never exported."""
import hashlib
import sqlite3
import unittest
from pathlib import Path

from harness.utils.ledger.db import Ledger, LedgerError, fingerprint, pinned
from harness.utils.ledger.export import snapshot, upload_call
from harness.tests import tree


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.root = tree(self, {})
        self.db, self.out = self.root / "harness.db", self.root / "out"
        ledger = Ledger.open(self.db)
        ledger.write(lambda con: con.execute("INSERT INTO pl_logs (uid, body, at) VALUES ('u', 'b', 1)"))
        ledger.close()

    def test_a_copy_is_whole_and_has_the_pinned_schema(self):
        copy = snapshot(self.db, self.out, "session_01AB/x", now=0)
        self.assertEqual(copy["title"], f"session-01AB-x__19700101T000000Z__nocommit__s{pinned()[:8]}.db")
        path = Path(copy["path"])
        self.assertEqual((path.parent, path.name), (self.out.resolve(), copy["title"]))
        self.assertEqual(copy["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(copy["size"], path.stat().st_size)
        con = sqlite3.connect(path)
        self.assertEqual(fingerprint(con), pinned())
        self.assertEqual(con.execute("SELECT uid, body FROM pl_logs").fetchall(), [("u", "b")])
        con.close()

    def test_the_name_carries_the_newest_commit_and_an_older_copy_goes(self):
        first = snapshot(self.db, self.out, "s1", now=0)
        other = snapshot(self.db, self.out, "s2", now=0)
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO rec_commits (plan_id, service, commit_sha, at) VALUES (1, 'u', 'abcdef0123456789', 5)")
        con.commit()
        con.close()
        second = snapshot(self.db, self.out, "s1", now=60)
        self.assertIn("__19700101T000100Z__abcdef0__", second["title"])
        self.assertFalse(Path(first["path"]).exists())  # one copy a session on the machine
        self.assertTrue(Path(other["path"]).exists())  # another session's copy stays
        self.assertEqual(sorted(p.name for p in self.out.iterdir()),
                         sorted([".gitignore", second["title"], other["title"]]))
        self.assertEqual((self.out / ".gitignore").read_text(encoding="utf-8"), "*\n")  # git never sees a copy

    def test_a_ledger_that_drifted_or_is_not_there_is_never_exported(self):
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE extra (x)")
        con.commit()
        con.close()
        with self.assertRaises(LedgerError) as e:
            snapshot(self.db, self.out, "s1")
        self.assertIn("schema", str(e.exception))
        self.assertEqual([p.name for p in self.out.iterdir()], [".gitignore"])  # nothing is left to upload
        with self.assertRaises(LedgerError):
            snapshot(self.root / "none.db", self.out, "s1")

    def test_the_answer_names_the_one_drive_call(self):
        copy = snapshot(self.db, self.out, "s1", now=0)
        text = upload_call(copy, "folder-id-123")
        for line in (f"  title: {copy['title']}", "  parentId: folder-id-123",
                     "  contentMimeType: application/x-sqlite3", "  disableConversionToGoogleType: true",
                     f"  base64Content: sha256:{copy['sha256']}:{copy['path']}"):
            self.assertIn(line, text.splitlines())


if __name__ == "__main__":
    unittest.main()
