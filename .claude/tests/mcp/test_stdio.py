"""h3.three-tools: the action table, the skill library, find, guide, run and the JSON-RPC server, each on its own."""
import io
import json
import unittest

from harness.mcp.actions.table import ActionTable
from harness.mcp.server.stdio import StdioServer
from harness.mcp.skills.library import SkillError, Skills
from harness.mcp.tools.find import Find
from harness.mcp.tools.guide import Guide
from harness.mcp.tools.run import Run
from harness.utils.contracts import McpAction
from tests import tree

SKILL = "---\nname: {name}\ndescription: {about}\n---\n# {name}\nThe body of {name}.\n"


def library(test, **skills):
    return Skills(tree(test, {f"{n}/SKILL.md": SKILL.format(name=n, about=a) for n, a in skills.items()}))


class Echo(McpAction):
    block, name, summary = "health", "echo", "Say a word back"
    args_schema = {"type": "object", "properties": {"word": {"type": "string"}, "loud": {"type": "boolean"}},
                   "required": ["word"]}

    def run(self, ctx, args):
        return args["word"].upper() if args.get("loud") else args["word"]


def table():
    t = ActionTable()
    t.add(Echo)
    return t


class StdioServerTest(unittest.TestCase):
    def server(self):
        skills = library(self, plan="Present the plan before an edit")
        return StdioServer("harness", "0.1", [Find(skills, table()), Guide(skills, table()), Run(table(), {})])

    def ask(self, method, params=None, id=1):
        return self.server().handle({"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}})

    def test_initialize_lists_and_ping(self):
        self.assertEqual(self.ask("initialize")["result"]["serverInfo"]["name"], "harness")
        names = [t["name"] for t in self.ask("tools/list")["result"]["tools"]]
        self.assertEqual(names, ["find", "guide", "run"])
        self.assertEqual(self.ask("ping")["result"], {})

    def test_a_call_answers_text_and_a_failure_is_an_error_result(self):
        ok = self.ask("tools/call", {"name": "run", "arguments": {"block": "health", "action": "echo", "args": {"word": "a"}}})
        self.assertEqual(ok["result"], {"content": [{"type": "text", "text": "a"}], "isError": False})
        bad = self.ask("tools/call", {"name": "run", "arguments": {"block": "nope", "action": "x"}})
        self.assertTrue(bad["result"]["isError"])

    def test_wrong_requests_get_json_rpc_errors_and_notifications_get_nothing(self):
        self.assertEqual(self.ask("nope")["error"]["code"], -32601)
        self.assertEqual(self.ask("tools/call", {"name": "nope"})["error"]["code"], -32602)
        self.assertIsNone(self.server().handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_a_malformed_request_is_an_error_answer_never_a_crash(self):
        for params in ([1], "x", {"name": ["x"]}, {"name": "run", "arguments": [1]}):
            with self.subTest(params=params):
                method = "tools/call" if isinstance(params, dict) else "initialize"
                answer = self.server().handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                self.assertEqual(answer["error"]["code"], -32602)

    def test_a_failure_inside_the_server_is_an_internal_error(self):
        server = self.server()
        server.tools = None  # breaks tools/list
        self.assertEqual(server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["error"]["code"], -32603)

    def test_serve_survives_a_deep_line_and_a_lone_surrogate(self):
        out = io.StringIO()
        lines = "[" * 200000 + "\n" + '{"jsonrpc":"2.0","id":"\\ud800","method":"ping"}\n' + \
            '{"jsonrpc":"2.0","id":3,"method":"ping"}\n'
        self.server().serve(io.StringIO(lines), out)
        answers = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([a.get("error", {}).get("code") for a in answers], [-32700, None, None])
        self.assertEqual(answers[2]["id"], 3)
        out.getvalue().encode("utf-8")  # what is written always encodes

    def test_serve_reads_lines_and_answers_lines(self):
        out = io.StringIO()
        self.server().serve(io.StringIO('{"jsonrpc":"2.0","id":7,"method":"ping"}\nnot json\n\n'), out)
        first, second = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual((first["id"], second["error"]["code"]), (7, -32700))


if __name__ == "__main__":
    unittest.main()
