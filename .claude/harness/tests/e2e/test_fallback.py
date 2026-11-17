"""The fallback in the anchor: a release that crashes its hook is left for the previous one by itself; the anchor's own
MCP server, fallback, rolls back a release that refuses everything; its calls pass the hook without loading a
release; a refusal stays a refusal."""
import json
import shutil
import unittest

from harness.tests.e2e import copy_tree, run

REFUSE_ALL = 'import sys\nsys.stderr.write("refused: everything\\n")\nsys.exit(2)\n'
CRASH_AT_LOAD = 'raise RuntimeError("a broken release")\n'
CRASH_FLAG = ('import os, sys\nos.environ["HARNESS_HOOK_FAILED"] = "1"\nsys.stderr.write("harness hook failed\\n")\n'
              'sys.exit(2)\n')


def event(tool, cwd):
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"pattern": "*.md"},
                       "session_id": "t-fallback", "cwd": str(cwd)})


class FallbackTest(unittest.TestCase):
    def setUp(self):
        self.root = copy_tree(self)
        self.anchor = self.root.parent / "anchor.py"
        self.live = self.root / "state" / "live"
        shutil.copytree(self.root / "harness", self.live / "good" / "harness",
                        ignore=shutil.ignore_patterns("__pycache__"))

    def broken(self, hook_text):
        """A release 'new' in force whose hook is hook_text, with 'good' as the previous release."""
        shutil.copytree(self.live / "good" / "harness", self.live / "new" / "harness")
        (self.live / "new" / "harness" / "entry" / "hook.py").write_text(hook_text, encoding="utf-8")
        (self.live / "current").write_text("new", encoding="utf-8")
        (self.live / "previous").write_text("good", encoding="utf-8")

    def live_file(self, name):
        path = self.live / name
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""

    def hook(self, tool):
        return run(self.anchor, event(tool, self.root.parent), ["hook"])

    def test_a_hook_that_crashes_at_load_falls_back_to_the_previous_release(self):
        self.broken(CRASH_AT_LOAD)
        code, out, err = self.hook("Glob")
        self.assertEqual(self.live_file("current"), "good", err)
        self.assertIn("new", self.live_file("bad").split())
        self.assertEqual(self.live_file("previous"), "")  # one step back only: never back again by itself
        self.assertIn("fell back", err)
        self.assertNotIn("a broken release", out)

    def test_a_hook_that_says_it_failed_falls_back_too(self):
        self.broken(CRASH_FLAG)
        code, out, err = self.hook("Glob")
        self.assertEqual(self.live_file("current"), "good", err)
        self.assertIn("new", self.live_file("bad").split())

    def test_a_refusal_stays_a_refusal(self):
        self.broken(REFUSE_ALL)
        code, out, err = self.hook("Glob")
        self.assertEqual(code, 2)
        self.assertIn("refused: everything", err)
        self.assertEqual(self.live_file("current"), "new")
        self.assertEqual(self.live_file("bad"), "")

    def test_the_fallback_server_rolls_back_a_release_that_refuses_everything(self):
        self.broken(REFUSE_ALL)
        code, out, err = self.hook("mcp__fallback__rollback")  # its call passes without loading a release
        self.assertEqual(code, 0, err)
        lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
                 {"jsonrpc": "2.0", "method": "notifications/initialized"},
                 {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                 {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": "rollback", "arguments": {"why": "every call is refused"}}},
                 {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "status", "arguments": {}}}]
        code, out, err = run(self.anchor, "".join(json.dumps(x) + "\n" for x in lines), ["fallback"])
        self.assertEqual(code, 0, err)
        answers = {a["id"]: a for a in map(json.loads, out.splitlines())}
        self.assertEqual(sorted(answers), [1, 2, 3, 4])  # a notification gets no answer
        self.assertEqual(answers[1]["result"]["serverInfo"]["name"], "fallback")
        self.assertEqual({t["name"] for t in answers[2]["result"]["tools"]}, {"rollback", "status"})
        self.assertIn("good", answers[3]["result"]["content"][0]["text"])
        self.assertIn("In force: good", answers[4]["result"]["content"][0]["text"])
        self.assertEqual(self.live_file("current"), "good")
        self.assertIn("new", self.live_file("bad").split())
        self.assertIn("every call is refused", self.live_file("fallback.log"))

    def test_a_rollback_with_no_previous_release_changes_nothing(self):
        self.broken(REFUSE_ALL)
        (self.live / "previous").unlink()
        call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "rollback", "arguments": {}}}
        code, out, err = run(self.anchor, json.dumps(call) + "\n", ["fallback"])
        answer = json.loads(out.splitlines()[0])
        self.assertTrue(answer["result"]["isError"])
        self.assertEqual(self.live_file("current"), "new")


if __name__ == "__main__":
    unittest.main()
