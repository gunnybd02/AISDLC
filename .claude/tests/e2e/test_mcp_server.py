"""h3.three-tools (AC4): entry/mcp_server.py run as Claude Code runs it answers initialize, tools/list, find, guide
and run over stdio."""
import json
import subprocess
import sys
import unittest

import harness.mcp as mcp_block
from tests import CLAUDE_DIR
from tests.e2e import copy_tree, run

SCRIPT = CLAUDE_DIR / "entry" / "mcp_server.py"


def request(id, method, params=None):
    return json.dumps({"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}})


def call(id, tool, arguments):
    return request(id, "tools/call", {"name": tool, "arguments": arguments})


class McpServerEntryTest(unittest.TestCase):
    def test_the_server_answers_the_three_tools(self):
        lines = [request(1, "initialize", {"protocolVersion": "2025-06-18"}),
                 json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                 request(2, "tools/list"),
                 call(3, "find", {"query": "example skill"}),
                 call(4, "guide", {"name": "example", "mode": "skills"}),
                 call(5, "guide", {"name": "health", "mode": "mcp"}),
                 call(6, "run", {"block": "health", "action": "items"})]
        code, out, err = run(SCRIPT, "\n".join(lines) + "\n")
        self.assertEqual(code, 0, err)
        answers = {a["id"]: a for a in map(json.loads, out.splitlines())}
        self.assertEqual(sorted(answers), [1, 2, 3, 4, 5, 6])
        self.assertEqual(answers[1]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual([t["name"] for t in answers[2]["result"]["tools"]], ["find", "guide", "run"])
        text = {i: answers[i]["result"]["content"][0]["text"] for i in (3, 4, 5, 6)}
        self.assertIn("[skills] example", text[3])
        self.assertIn("name: example", text[4])
        self.assertIn("items()", text[5])
        self.assertIn("gear rule decide", text[6])

    def test_bytes_that_are_not_utf8_do_not_stop_the_server(self):
        stdin = b'{"jsonrpc":"2.0","id":1,"method":"ping","x":"\xff\xfe"}\n' + request(2, "ping").encode() + b"\n"
        p = subprocess.run([sys.executable, str(SCRIPT)], input=stdin, capture_output=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual([json.loads(line)["id"] for line in p.stdout.decode().splitlines()], [1, 2])

    def test_a_harness_that_exits_quietly_exits_2(self):
        root = copy_tree(self, {"harness/assemble/build.py": "raise SystemExit(0)\n"})
        self.assertEqual(run(root / "entry" / "mcp_server.py", request(1, "ping"))[0], 2)

    def test_the_server_tools_are_declared_by_mcp(self):
        names = {i["name"] for i in mcp_block.ITEMS}
        self.assertLessEqual({"stdio", "find", "guide", "run", "skills", "action_table"}, names)


if __name__ == "__main__":
    unittest.main()
