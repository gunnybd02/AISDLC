"""h11.one-store: the ledger is read only through db_query, one read-only SELECT that never reads transcripts."""
import gzip
import json
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
        self.work = tree(self, {})  # the session's working folder

    def export(self, folder_env="", **args):
        with mock.patch.dict(os.environ, {"HARNESS_DRIVE_FOLDER": folder_env}):
            return self.run_action("ledger", "export", **{"into": str(self.work), **args})

    def test_with_no_store_folder_nothing_is_copied(self):
        for result in (self.export(), self.export(folder="no")):
            self.assertTrue(result.is_error)
            self.assertIn("HARNESS_DRIVE_FOLDER", result.text)
        self.assertFalse((self.work / ".harness-export").exists())
        lost = self.export("folder-from-env-1", into=str(self.work / "none"))
        self.assertTrue(lost.is_error)
        self.assertIn("is not a folder", lost.text)

    def test_the_answer_is_the_drive_call_of_a_copy_that_holds_its_own_record(self):
        for result, folder in ((self.export("folder-from-env-1"), "folder-from-env-1"),
                               (self.export("folder-from-env-1", folder="folder-given-22", reason="push"),
                                "folder-given-22")):
            self.assertFalse(result.is_error, result.text)
            self.assertIn(f"parentId = '{folder}'", result.text)  # db is found (or made) in that folder first
            self.assertIn("  parentId: <the id of the db folder Drive gave>", result.text.splitlines())
            self.assertIn("create_file", result.text)
        (copy,) = (self.work / ".harness-export").glob("s-export-test__*.db.gz")  # one copy a session, gzipped
        self.assertRegex(copy.name,
                         r"^s-export-test__[0-9a-f]{6}-002__\d{8}T\d{6}Z__push__nocommit__s[0-9a-f]{8}\.db\.gz$")
        self.assertEqual((self.work / ".harness-export" / ".gitignore").read_text(encoding="utf-8"), "*\n")
        self.assertIn(copy.resolve().as_posix(), result.text)
        plain = self.work / "plain.db"
        plain.write_bytes(gzip.decompress(copy.read_bytes()))
        con = sqlite3.connect(plain)
        self.assertEqual(con.execute("SELECT uid FROM pl_logs").fetchall(), [("u",)])
        (text,) = con.execute("SELECT text FROM pl_notes WHERE kind = 'store.export' AND key = '2'").fetchone()
        con.close()
        inside = json.loads(text)  # the copy says by itself who made it, when and why
        self.assertEqual((inside["title"] + ".gz", inside["seq"], inside["session"], inside["reason"]),
                         (copy.name, 2, "s-export-test", "push"))
        self.assertTrue(self.export("folder-from-env-1", reason="later").is_error)

    def test_without_into_the_copy_goes_to_the_folder_the_call_is_made_from(self):
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.work)
        with mock.patch.dict(os.environ, {"HARNESS_DRIVE_FOLDER": "folder-from-env-1"}):
            result = self.run_action("ledger", "export")
        self.assertFalse(result.is_error, result.text)
        self.assertEqual(len(list((self.work / ".harness-export").glob("*.db.gz"))), 1)

    def test_the_status_reads_the_store_and_the_note_follows_a_push_only_with_a_store(self):
        from harness.mcp.actions.ledger import STORE_NOTE, store_note
        from harness.utils.contracts import ActionContext
        self.export("folder-from-env-1")
        result = self.run_action("ledger", "store_status")
        self.assertFalse(result.is_error, result.text)
        self.assertIn("Newest copy made: 1 - s-export-test__", result.text)
        self.assertIn("Newest copy in the store: none.", result.text)
        self.assertEqual(store_note(ActionContext({"store": lambda: ""})), "")
        self.assertEqual(store_note(ActionContext({"store": lambda: "folder-id-123"})), STORE_NOTE)
        self.assertIn("run('ledger', 'export', {reason: 'push'})", STORE_NOTE)


class ChainAndAnnotateTest(unittest.TestCase):
    def setUp(self):
        import uuid
        self.root = copy_tree(self)  # a write action meets the real judge of this tree
        self.port = LedgerPort(self.root)
        self.port.touch_session("s1")

        def fill(con, rec):
            for n in (1, 2, 3):
                rec.insert(con, "rec_commits", {"plan_id": 1, "service": "r", "commit_sha": f"sha{n}", "at": n, "uid": uuid.uuid4().hex})
                rec.insert(con, "pl_file_grants", {"uid": uuid.uuid4().hex, "sid": "s1", "plan_id": 1, "op": "add",
                                                   "file": f"/r/f{n}.py", "why": "w", "at": n})
        self.port.write(fill)
        self.run = caller(self.root)

    def test_chain_check_passes_on_a_whole_ledger_and_names_the_table_and_row_of_an_edited_row(self):
        from harness.assemble.engine.checks import chains
        said = self.run("ledger", "chain_check").text
        self.assertIn("rec_commits: 3 row(s), whole", said)
        self.assertIn("pl_verify: 0 row(s), whole", said)
        self.assertTrue(said.endswith("Every chain is whole."))
        self.assertEqual(chains(self.root), [])
        self.port.write(lambda con, rec: con.execute("UPDATE rec_commits SET commit_sha = 'other' WHERE commit_sha = 'sha2'"))
        self.port.write(lambda con, rec: con.execute("UPDATE pl_file_grants SET why = 'changed' WHERE file = '/r/f3.py'"))
        said = self.run("ledger", "chain_check").text
        self.assertIn("rec_commits: 3 row(s), BROKEN at row 2", said)
        self.assertIn("pl_file_grants: 3 row(s), BROKEN at row 3", said)
        self.assertIn("rec_plans: 0 row(s), whole", said)
        self.assertIn("2 chain(s) broken: a row was changed after it was written.", said)
        self.assertEqual(chains(self.root), [
            "ledger: rec_commits row 2 breaks its hash chain (a row was changed after it was written)",
            "ledger: pl_file_grants row 3 breaks its hash chain (a row was changed after it was written)"])
        self.assertEqual(chains(tree(self, {})), [])  # a home with no ledger has no chain to report

    def test_annotate_keeps_a_row_marked_as_the_models_and_a_missing_field_keeps_nothing(self):
        key = "ghp_" + "a1B2c3D4" * 5  # the shape of a token, not one
        kept = self.run("ledger", "annotate", unit="plan", ref="pd-x" + "y" * 200, name="open:retry-after-deny",
                        identifier="pr-2026-11-16", label="seen", score=3, explanation="tried  the same\ntool again")
        self.assertEqual(kept.text[:5], "Kept:")
        self.assertFalse(self.run("ledger", "annotate", unit="turn", ref="7", name="n", identifier="i",
                                  explanation=f"the key {key}").is_error)
        rows = [dict(r) for r in self.port.rows("SELECT sid, unit, length(ref) AS ref, name, label, score, explanation, "
                                                "annotator, identifier FROM pl_annotations ORDER BY at, rowid")]
        self.assertEqual(rows[0], {"sid": "s1", "unit": "plan", "ref": 120, "name": "open:retry-after-deny", "label": "seen",
                                   "score": 3.0, "explanation": "tried the same tool again", "annotator": "LLM",
                                   "identifier": "pr-2026-11-16"})
        self.assertEqual((rows[1]["explanation"], rows[1]["score"], rows[1]["annotator"]), ("[redacted]", None, "LLM"))
        for bad, why in (({"unit": "plan", "ref": "x", "name": "n"}, "identifier"),
                         ({"unit": "plan", "ref": " ", "name": "n", "identifier": "i"}, "annotate needs ref"),
                         ({"unit": "repo", "ref": "x", "name": "n", "identifier": "i"}, "span, turn, session, plan")):
            result = self.run("ledger", "annotate", **bad)
            self.assertTrue(result.is_error)
            self.assertIn(why, result.text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.port.rows("SELECT COUNT(*) AS n FROM pl_annotations")[0]["n"], 2)  # nothing more was kept


if __name__ == "__main__":
    unittest.main()
