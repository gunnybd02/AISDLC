"""h24.store-life: a turn does not end while work of the ledger is in no copy of the store; it is held once for the
same work, never without a store folder, never when the harness cannot look."""
import unittest
from unittest import mock

from harness.assemble.engine.ports import LedgerPort, PlanState
from harness.assemble.engine.runner import Act
from harness.gear.decide.arbiter import Decide
from harness.gear.detect.store import StoreGuard
from harness.utils.contracts import Event, Finding, Verdict
from harness.utils.ledger import store
from harness.tests import CLAUDE_DIR, tree


class StoreGuardTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(tree(self, {}))
        self.port.touch_session("s1")
        self.port.write(lambda con, rec: rec.insert(con, "rec_commits", {
            "plan_id": 1, "service": "u", "commit_sha": "aaaaaaa1", "at": 1, "uid": "u1"}))

    def stop(self, active=False, folder="folder-id-123"):
        event = Event("Stop", "", {"stop_hook_active": active}, "s1")
        with mock.patch.dict("os.environ", {store.ENV: folder}):
            facts = PlanState(self.port).read(event)
            return [(f.kind, f.detail) for f in StoreGuard().detect(event, facts)]

    def test_a_turn_with_unsaved_work_is_held_once(self):
        self.assertEqual(self.stop(), [("store.unsaved", "1 commit(s)")])
        self.assertEqual(self.stop(active=True), [])  # the Stop repeated after the block ends the turn
        row = Decide.load(CLAUDE_DIR).rules["store.unsaved"]
        self.assertEqual(row["verdict"], "refuse")
        self.assertIn("run('ledger', 'export', {reason: 'turn-end'})", row["why"])
        held = Verdict("refuse", "why", (Finding("store.unsaved", "1 commit(s)"),))
        Act(self.port).run(Event("Stop", "", {"stop_hook_active": False}, "s1"), {}, held)
        self.assertEqual(self.stop(), [])  # held once for this work, whether or not it was uploaded

    def test_no_folder_no_work_or_no_look_never_holds_a_turn(self):
        self.assertEqual(self.stop(folder=""), [])  # the store is off
        record = store.begin(self.port, "s1", "turn-end")
        answer = {"id": "1AbCdEfGhIjKlMnOp", "title": record["title"]}
        Act(self.port).run(Event("PostToolUse", "mcp__Google_Drive__create_file", {"title": record["title"]}, "s1",
                                 "/w", answer), {}, Verdict("allow"))
        self.assertEqual(self.stop(), [])  # the store holds a copy made after the commit
        event = Event("Stop", "", {"stop_hook_active": False}, "s1")
        self.assertEqual(StoreGuard().detect(event, {"store_owed": lambda: 1 / 0}), [])
        self.assertEqual(StoreGuard().detect(event, {}), [])
        self.assertEqual(StoreGuard().detect(Event("PreToolUse", "Bash", {}, "s1"), {"store_owed": lambda: ["x"]}), [])


if __name__ == "__main__":
    unittest.main()
