"""h17.stop-guard: a turn may not end while a code file of the plan changed since the last green verify; a repeated
Stop, no plan, or nothing owed lets it end; a failure to look keeps it."""
import json
import unittest

from harness.assemble.engine.config import Config
from harness.assemble.engine.ports import LedgerPort
from harness.gear.detect.stop import StopGuard
from harness.hooks.io import HookIO
from harness.utils.contracts import YES, Event, Verdict
from harness.utils.plan import desk
from harness.utils.plan.approval import approvals
from harness.utils.plan.stop import unverified
from harness.utils.plan.verify import verify
from tests.e2e import copy_tree, git_repo, run

TEST = "import unittest\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\n"


class StopTest(unittest.TestCase):
    def setUp(self):
        self.claude_dir = copy_tree(self, {"project.json": json.dumps(
            {"name": "t", "verify": ["{python}", "-m", "unittest", "discover", "-s", "."]})})
        self.repo = git_repo(self, {"a.py": "X = 1\n", "test_a.py": TEST, "notes.md": "n\n"})
        self.port = LedgerPort(self.claude_dir)
        items = {**desk.normalize(desk.clean({"title": "Set the value", "what": ["w"], "files": ["a.py", "notes.md"],
                                              "tests": ["test_a.py"]})), "root": str(self.repo)}
        plan_id, _, q = self.port.present(items, sid="s1")
        approvals(self.port, "s1", {q: YES})
        self.plan_id = plan_id

    def stop(self, active=False, owed=None):
        plan = self.port.approved("s1")
        facts = {"plan": plan, "stop_owed": owed or (lambda p: unverified(self.port, p))}
        return [f.kind for f in StopGuard().detect(Event("Stop", "", {"stop_hook_active": active}, "s1"), facts)]

    def test_a_turn_with_unverified_code_does_not_end(self):
        self.assertEqual(self.stop(), [])
        (self.repo / "notes.md").write_text("more\n", encoding="utf-8")
        self.assertEqual(self.stop(), [])  # a .md owes nothing
        (self.repo / "a.py").write_text("X = 2\n", encoding="utf-8")
        self.assertEqual(self.stop(), ["stop.unverified"])
        self.assertEqual(self.stop(active=True), [])  # the repeated Stop ends the turn
        verify(self.port, Config.load(self.claude_dir).verify, self.plan_id)
        self.assertEqual(self.stop(), [])
        (self.repo / "a.py").write_text("X = 3\n", encoding="utf-8")
        self.assertEqual(self.stop(), ["stop.unverified"])

    def test_a_failure_to_look_keeps_the_turn(self):
        def broken(plan):
            raise OSError("disk")
        self.assertEqual(self.stop(owed=broken), ["stop.unverified"])

    def test_no_plan_no_guard(self):
        event = Event("Stop", "", {"stop_hook_active": False}, "s2")
        self.assertEqual(StopGuard().detect(event, {"plan": None}), [])

    def test_the_hook_answers_a_block_claude_code_reads(self):
        out = json.loads(HookIO.write(Event("Stop"), Verdict("refuse", "verify first")))
        self.assertEqual(out, {"decision": "block", "reason": "verify first"})
        self.assertEqual(HookIO.read(json.dumps({"hook_event_name": "Stop", "stop_hook_active": True})).input,
                         {"stop_hook_active": True})
        (self.repo / "a.py").write_text("X = 2\n", encoding="utf-8")
        code, out, _ = run(self.claude_dir / "entry" / "hook.py", json.dumps(
            {"hook_event_name": "Stop", "session_id": "s1", "cwd": str(self.repo), "stop_hook_active": False}))
        self.assertEqual((code, json.loads(out)["decision"]), (0, "block"))
        self.assertIn("a.py", json.loads(out)["reason"])


if __name__ == "__main__":
    unittest.main()
