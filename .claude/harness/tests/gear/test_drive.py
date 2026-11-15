"""h23.store: the store on Google Drive only grows. Trashing a Drive file, or moving or renaming one, asks the user;
uploading, reading and searching are free, and so is every tool that is not a Drive server's."""
import unittest

from harness.gear.decide.arbiter import Decide
from harness.gear.detect.drive import DriveGuard
from harness.utils.contracts import Event
from harness.tests import CLAUDE_DIR


def found(tool, given=None, kind="PreToolUse"):
    return [(f.kind, f.detail) for f in DriveGuard().detect(Event(kind, tool, given or {}, "s1"), {})]


class DriveTest(unittest.TestCase):
    def test_trashing_a_drive_file_asks_the_user(self):
        for tool in ("mcp__Google_Drive__trash_file", "mcp__gdrive__delete_file", "mcp__claude_ai_Google_Drive__trash_file"):
            with self.subTest(tool=tool):
                self.assertEqual(found(tool, {"fileId": "f1"}), [("drive.remove", "f1")])
        self.assertEqual(Decide.load(CLAUDE_DIR).rules["drive.remove"]["verdict"], "ask")

    def test_moving_or_renaming_a_drive_file_asks_the_user(self):
        self.assertEqual(found("mcp__Google_Drive__update_file", {"fileId": "f1", "title": "x.db"}), [("drive.move", "f1")])
        self.assertEqual(found("mcp__Google_Drive__update_file", {"fileId": "f1", "parentId": "p"}), [("drive.move", "f1")])
        self.assertEqual(found("mcp__Google_Drive__update_file", {"fileId": "f1", "starred": True}), [])
        self.assertEqual(Decide.load(CLAUDE_DIR).rules["drive.move"]["verdict"], "ask")

    def test_uploading_reading_and_other_tools_are_free(self):
        for tool, given in (("mcp__Google_Drive__create_file", {"title": "a.db", "parentId": "p"}),
                            ("mcp__Google_Drive__search_files", {"query": "x"}),
                            ("mcp__Google_Drive__download_file_content", {"fileId": "f1"}),
                            ("mcp__harness__run", {"block": "ledger", "action": "export"}),
                            ("mcp__Google_Docs__update_doc", {"title": "x"}), ("Bash", {"command": "rm drive"}),
                            ("trash_file", {"fileId": "f1"})):
            with self.subTest(tool=tool):
                self.assertEqual(found(tool, given), [])
        self.assertEqual(found("mcp__Google_Drive__trash_file", {"fileId": "f1"}, kind="PostToolUse"), [])


if __name__ == "__main__":
    unittest.main()
