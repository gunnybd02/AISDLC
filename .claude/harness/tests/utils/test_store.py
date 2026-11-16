"""h24.store-life: the ledger knows its copies. A copy has a record (ledger, number, session, reason, time, commit)
kept before it is made; the hook keeps that the store holds it when a Drive tool answers with the file; work is
unsaved while commits, plan events or pushes are in no copy the store holds; a turn is held once for the same work."""
import json
import unittest
from unittest import mock

from harness.assemble.engine.ports import LedgerPort
from harness.utils.contracts import Event
from harness.utils.ledger import store
from harness.tests import tree

DRIVE = "mcp__Google_Drive__create_file"


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(tree(self, {}))
        self.port.touch_session("s1")

    def commit(self, sha):
        self.port.write(lambda con, rec: rec.insert(con, "rec_commits", {
            "plan_id": 1, "service": "u", "commit_sha": sha, "at": len(sha), "uid": sha}))

    def upload(self, record, answer=None, tool=DRIVE):
        answer = {"id": "1AbCdEfGhIjKlMnOp", "title": record["title"]} if answer is None else answer
        return store.uploaded(self.port, Event("PostToolUse", tool, {"title": record["title"]}, "s1", "/w", answer))

    def test_a_copy_has_a_record_and_a_name_that_say_who_and_when(self):
        self.commit("abcdef0123456789")
        first = store.begin(self.port, "session_01AB", "push", {"repo": "app", "branch": "work"}, now=0)
        second = store.begin(self.port, "session_01AB", "turn-end", now=60)
        ledger = first["ledger"]
        self.assertEqual((first["seq"], second["seq"], second["ledger"]), (1, 2, ledger))  # one ledger, numbered copies
        self.assertEqual(first["title"],
                         f"session-01AB__{ledger[:6]}-001__19700101T000000Z__push__abcdef0__{first['schema']}.db")
        self.assertIn(f"__{ledger[:6]}-002__19700101T000100Z__turn-end__", second["title"])
        (row,) = self.port.rows("SELECT text FROM pl_notes WHERE kind = 'store.export' AND key = '1'")
        kept = json.loads(row["text"])  # the record is in the ledger, so the copy made next holds it
        self.assertEqual({k: kept[k] for k in ("ledger", "seq", "session", "reason", "commit", "repo", "branch", "mark")},
                         {"ledger": ledger, "seq": 1, "session": "session_01AB", "reason": "push",
                          "commit": "abcdef0", "repo": "app", "branch": "work", "mark": [1, 0, 0]})
        self.assertEqual(len(self.port.rows("SELECT 1 AS x FROM pl_notes WHERE kind = 'store.ledger'")), 1)

    def test_the_store_holds_a_copy_only_when_drive_answers_with_its_file(self):
        record = store.begin(self.port, "s1", "manual")
        refused = f"Nothing was uploaded: /w/.harness-export/{record['title']} either does not exist or can't be sent"
        for answer, tool in ((refused, DRIVE), ({"id": "1AbCdEfGhIjKlMnOp", "title": "other.db"}, DRIVE),
                             ({"title": record["title"]}, DRIVE), (None, "mcp__Google_Drive__search_files"),
                             (None, "create_file")):
            with self.subTest(answer=answer, tool=tool):
                self.assertEqual(self.upload(record, answer, tool), [])
        self.assertIsNone(store.saved(self.port))
        text = json.dumps({"id": "1AbCdEfGhIjKlMnOp", "title": record["title"], "fileSize": "9"})
        for answer in ([{"type": "text", "text": text}], text):  # as a tool's content blocks, or as plain text
            self.assertEqual(self.upload(record, answer), [f"The store holds copy 1 of this ledger: {record['title']}."])
        held = store.saved(self.port)
        self.assertEqual((held["seq"], held["title"], held["file_id"]), (1, record["title"], "1AbCdEfGhIjKlMnOp"))
        second = store.begin(self.port, "s1", "manual")  # a connector Claude Code names by its id, a plain JSON answer
        by_id = "mcp__caaed075-fab9-4852-ba97-a638e8eac9e4__create_file"
        text = json.dumps({"fileSize": "409600", "id": "1o4T5wPp6eX9DAvKctWEdmzH8bD6", "title": second["title"]},
                          separators=(",", ":"))
        self.assertEqual(self.upload(second, text, by_id), [f"The store holds copy 2 of this ledger: {second['title']}."])
        self.assertEqual(store.saved(self.port)["file_id"], "1o4T5wPp6eX9DAvKctWEdmzH8bD6")
        self.assertEqual(len(self.port.rows("SELECT 1 AS x FROM pl_notes WHERE kind = 'store.uploaded'")), 2)

    def test_work_is_unsaved_until_a_copy_made_after_it_is_in_the_store(self):
        self.assertEqual(store.unsaved(self.port), [])  # an empty ledger owes nothing
        self.commit("aaaaaaa1")
        self.commit("bbbbbbb2")
        self.assertEqual(store.unsaved(self.port), ["2 commit(s)"])
        record = store.begin(self.port, "s1", "turn-end")
        self.assertEqual(store.unsaved(self.port), ["2 commit(s)"])  # made, not uploaded yet
        self.upload(record)
        self.assertEqual(store.unsaved(self.port), [])
        self.commit("ccccccc3")
        self.assertEqual(store.unsaved(self.port), ["1 commit(s)"])  # newer work than the copy the store holds

    def test_a_turn_is_held_once_for_the_same_work(self):
        self.commit("aaaaaaa1")
        self.assertEqual(store.owed(self.port), ["1 commit(s)"])
        store.asked(self.port, "s1")
        self.assertEqual(store.owed(self.port), [])  # the session could not upload: it is not asked again
        self.commit("bbbbbbb2")
        self.assertEqual(store.owed(self.port), ["2 commit(s)"])  # new work asks again

    def test_the_status_says_what_the_store_holds_and_what_waits(self):
        with mock.patch.dict("os.environ", {store.ENV: ""}):
            self.assertIn("Store folder: not set (HARNESS_DRIVE_FOLDER).", store.status(self.port))
        self.commit("aaaaaaa1")
        record = store.begin(self.port, "s1", "push")
        self.upload(record)
        self.commit("bbbbbbb2")
        with mock.patch.dict("os.environ", {store.ENV: "folder-id-123"}):
            lines = store.status(self.port).splitlines()
        self.assertEqual(lines[0], "Store folder: set.")
        self.assertEqual(lines[1], f"Ledger: {record['ledger']}.")
        self.assertEqual(lines[3], f"Newest copy in the store: 1 - {record['title']} (Drive file 1AbCdEfGhIjKlMnOp).")
        self.assertEqual(lines[4], "Not in the store yet: 1 commit(s).")


if __name__ == "__main__":
    unittest.main()
