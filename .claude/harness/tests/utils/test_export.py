"""h23.store: a ledger's copy for the store outside the machine is whole, has the pinned schema, and takes the name of
the store's record; a ledger whose schema drifted is never exported."""
import gzip
import hashlib
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from harness.utils.ledger import export
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

    def record(self, title, session="s1"):
        return {"title": title, "session": session}

    def test_a_copy_is_whole_and_has_the_pinned_schema(self):
        """s1.export.gzip: the file is the copy gzipped; it unzips to the whole ledger of the pinned schema."""
        copy = snapshot(self.db, self.out, self.record("session-01AB__x-001__t__push__nocommit__s1.db", "session_01AB"))
        path = Path(copy["path"])
        self.assertEqual((path.parent, path.name), (self.out.resolve(), copy["title"]))
        self.assertEqual(copy["title"], "session-01AB__x-001__t__push__nocommit__s1.db.gz")
        self.assertEqual(copy["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(copy["size"], path.stat().st_size)
        plain = self.root / "plain.db"
        plain.write_bytes(gzip.decompress(path.read_bytes()))
        con = sqlite3.connect(plain)
        self.assertEqual(fingerprint(con), pinned())
        self.assertEqual(con.execute("SELECT uid, body FROM pl_logs").fetchall(), [("u", "b")])
        con.close()
        self.assertLess(copy["size"], plain.stat().st_size)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), [".gitignore", copy["title"]])  # no plain copy left

    def test_a_copy_too_big_for_one_drive_call_is_refused_with_its_size(self):
        """s1.export.too-big"""
        with mock.patch.object(export, "MOST", 10):
            with self.assertRaises(LedgerError) as e:
                snapshot(self.db, self.out, self.record("s1__x-001__a.db"))
        self.assertIn("bytes gzipped, over the 10 one Drive call carries", str(e.exception))
        self.assertEqual([p.name for p in self.out.iterdir()], [".gitignore"])  # nothing is left to upload

    def test_an_older_copy_of_the_session_goes_and_git_never_sees_the_folder(self):
        first = snapshot(self.db, self.out, self.record("s1__x-001__a.db"))
        other = snapshot(self.db, self.out, self.record("s2__x-002__b.db", "s2"))
        second = snapshot(self.db, self.out, self.record("s1__x-003__c.db"))
        self.assertFalse(Path(first["path"]).exists())  # one copy a session on the machine
        self.assertTrue(Path(other["path"]).exists())  # another session's copy stays
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), [".gitignore", second["title"], other["title"]])
        self.assertEqual((self.out / ".gitignore").read_text(encoding="utf-8"), "*\n")

    def test_a_ledger_that_drifted_or_is_not_there_is_never_exported(self):
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE extra (x)")
        con.commit()
        con.close()
        with self.assertRaises(LedgerError) as e:
            snapshot(self.db, self.out, self.record("s1__x-001__a.db"))
        self.assertIn("schema", str(e.exception))
        self.assertEqual([p.name for p in self.out.iterdir()], [".gitignore"])  # nothing is left to upload
        with self.assertRaises(LedgerError):
            snapshot(self.root / "none.db", self.out, self.record("s1__x-001__a.db"))

    def test_the_answer_names_the_one_drive_call(self):
        """s2.export.db: into the db folder when it is known; else first the calls that find or make it."""
        copy = snapshot(self.db, self.out, self.record("s1__x-001__a.db"))
        text = upload_call(copy, "folder-id-123", "db-folder-456")
        for line in (f"  title: {copy['title']}", "  parentId: db-folder-456",
                     "  contentMimeType: application/gzip", "  disableConversionToGoogleType: true",
                     f"  base64Content: sha256:{copy['sha256']}:{copy['path']}"):
            self.assertIn(line, text.splitlines())
        self.assertNotIn("First find", text)
        first = upload_call(copy, "folder-id-123")
        self.assertIn("First find the store's db folder", first)
        self.assertIn("parentId = 'folder-id-123'", first)
        self.assertIn("  parentId: <the id of the db folder Drive gave>", first.splitlines())


if __name__ == "__main__":
    unittest.main()
