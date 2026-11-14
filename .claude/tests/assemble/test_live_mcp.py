"""h21.release: boot runs the release in force, never the work tree a session edits; the MCP server follows a newly
published release without a restart, after its doctor; a release whose doctor fails is never swapped in; publishing
needs the user's Cho phép of exactly that sha."""
import json
import re
import subprocess
import sys
import unittest

from harness.assemble.engine.cli_live import publish_door, status
from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.utils.contracts import Event, Verdict
from harness.utils.gateway.release import build, current, publish
from tests.e2e import copy_tree, run

ITEMS_SUMMARY = "Every problem of the tree: the indexes, the build, the skills, the nets"


def call(n, block_name):
    return json.dumps({"jsonrpc": "2.0", "id": n, "method": "tools/call",
                       "params": {"name": "guide", "arguments": {"name": block_name, "mode": "mcp"}}}) + "\n"


class LiveTest(unittest.TestCase):
    def setUp(self):
        self.home = copy_tree(self)
        sha = build(self.home)
        publish(self.home, sha)
        self.first = sha

    def edit_health_summary(self, text):
        path = self.home / "harness" / "mcp" / "actions" / "health.py"
        path.write_text(path.read_text().replace(ITEMS_SUMMARY, text))

    def test_boot_runs_the_release_not_the_work_tree(self):
        (self.home / "harness" / "assemble" / "engine" / "build.py").write_text("raise RuntimeError('half made')\n")
        code, out, err = run(self.home / "entry" / "boot.py", json.dumps(
            {"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {}, "session_id": "s", "cwd": "/tmp"}),
            args=("hook",))
        self.assertEqual((code, out), (0, ""), err)  # the half-made work tree never runs
        self.assertEqual(run(self.home / "entry" / "hook.py", "{}")[0], 2)  # run directly, the work tree is broken

    def test_the_mcp_server_follows_a_published_release_without_a_restart(self):
        server = subprocess.Popen([sys.executable, str(self.home / "entry" / "boot.py"), "mcp_server"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
        self.addCleanup(server.kill)

        def ask(n):
            server.stdin.write(call(n, "health"))
            server.stdin.flush()
            return json.loads(server.stdout.readline())["result"]["content"][0]["text"]

        self.assertIn(ITEMS_SUMMARY, ask(1))
        self.edit_health_summary("Every problem of the tree, as the doctor sees it")
        self.assertIn(ITEMS_SUMMARY, ask(2))  # the work tree alone changes nothing
        publish(self.home, build(self.home))
        self.assertIn("as the doctor sees it", ask(3))  # the new release, no restart
        bad = self.home / "harness" / "mcp" / "actions" / "broken.py"
        bad.write_text("ACTIONS = [(\"health.x\", \"Missing\")]\n")
        broken = build(self.home)
        publish(self.home, broken)
        self.assertIn("as the doctor sees it", ask(4))  # its doctor fails: never swapped in
        self.assertEqual(current(self.home), broken)

    def test_publish_needs_the_doctor_and_the_users_word(self):
        port = LedgerPort(self.home)
        self.edit_health_summary("The health of the harness, read by the doctor")
        code, text = publish_door(port, self.home)
        self.assertEqual(code, 0)
        q = re.search(r"exactly: (.+?\?) Options", text).group(1)
        self.assertEqual(current(self.home), self.first)  # asked, not published
        self.assertIn("not published", status(self.home))
        event = Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": q}]}, "s1", "/tmp")
        self.assertIn("allows publishing", " ".join(Act(port).run(event, {"answers": {q: "Cho phép"}},
                                                                    Verdict("allow"))))
        self.assertIn("is in force", publish_door(port, self.home)[1])
        self.assertNotEqual(current(self.home), self.first)
        self.assertIn("(published)", status(self.home))
        (self.home / "harness" / "mcp" / "actions" / "broken.py").write_text("ACTIONS = [(\"health.x\", \"Missing\")]\n")
        self.assertEqual(publish_door(port, self.home)[0], 1)  # its doctor finds a problem


if __name__ == "__main__":
    unittest.main()
