"""h3.three-tools: the action table, the skill library, find, guide, run and the JSON-RPC server, each on its own."""
import io
import json
import unittest

from harness.mcp.actions import ActionTable
from harness.mcp.find_tool import Find
from harness.mcp.guide_tool import Guide
from harness.mcp.run_tool import Run
from harness.mcp.skills import SkillError, Skills
from harness.mcp.stdio import StdioServer
from tests import tree

SKILL = "---\nname: {name}\ndescription: {about}\n---\n# {name}\nThe body of {name}.\n"


def library(test, **skills):
    return Skills(tree(test, {f"{n}/SKILL.md": SKILL.format(name=n, about=a) for n, a in skills.items()}))


def table():
    t = ActionTable()
    t.add_block("health", "The health of the harness")
    t.add("health", "echo", "Say a word back", {"word": "string", "loud?": "boolean"},
          lambda word, loud=False: word.upper() if loud else word)
    return t


class ActionTableTest(unittest.TestCase):
    def test_an_action_checks_its_arguments(self):
        echo = table().action("health", "echo")
        self.assertEqual(echo.problem({"word": "hi"}), "")
        self.assertIn("word", echo.problem({}))
        self.assertIn("string", echo.problem({"word": 3}))
        self.assertIn("other", echo.problem({"word": "hi", "other": 1}))

    def test_an_action_shows_its_signature(self):
        self.assertEqual(table().action("health", "echo").signature(), "echo(word: string, loud?: boolean)")

    def test_an_action_of_a_block_that_does_not_exist_is_refused(self):
        with self.assertRaises(KeyError):
            table().add("nowhere", "x", "x", {}, lambda: "")


class SkillsTest(unittest.TestCase):
    def test_the_library_reads_name_description_and_text(self):
        skill = library(self, plan="Present the plan before an edit").get("plan")
        self.assertEqual((skill.name, skill.description), ("plan", "Present the plan before an edit"))
        self.assertIn("The body of plan.", skill.text)

    def test_a_skill_without_frontmatter_is_refused(self):
        with self.assertRaises(SkillError):
            Skills(tree(self, {"bad/SKILL.md": "# no frontmatter\n"})).all()


class FindGuideRunTest(unittest.TestCase):
    def setUp(self):
        self.skills = library(self, plan="Present the plan before an edit", review="Review a change before commit")

    def test_find_ranks_skills_and_blocks_by_the_words_of_the_request(self):
        out = Find(self.skills, table()).call({"query": "plan an edit"}).text
        self.assertTrue(out.startswith("[skills] plan"))
        self.assertNotIn("review", out.split("\n")[0])
        self.assertIn("[mcp] health", Find(self.skills, table()).call({"query": "health"}).text)

    def test_find_narrows_by_mode_and_says_when_nothing_fits(self):
        self.assertNotIn("[mcp]", Find(self.skills, table()).call({"query": "health plan", "mode": "skills"}).text)
        self.assertTrue(Find(self.skills, table()).call({"query": "zzz"}).text.startswith("Nothing fits"))

    def test_guide_reads_a_skill_a_block_or_one_action(self):
        guide = Guide(self.skills, table())
        self.assertIn("The body of plan.", guide.call({"name": "plan", "mode": "skills"}).text)
        self.assertIn("echo(word: string, loud?: boolean)", guide.call({"name": "health", "mode": "mcp"}).text)
        self.assertIn("Say a word back", guide.call({"name": "health", "mode": "mcp", "topic": "echo"}).text)
        self.assertTrue(guide.call({"name": "nothing", "mode": "skills"}).is_error)

    def test_run_calls_only_an_action_of_the_table_with_right_arguments(self):
        run = Run(table())
        self.assertEqual(run.call({"block": "health", "action": "echo", "args": {"word": "hi", "loud": True}}).text, "HI")
        for args in ({"block": "health", "action": "rm"}, {"block": "x", "action": "echo"},
                     {"block": "health", "action": "echo", "args": {}}):
            with self.subTest(args=args):
                self.assertTrue(run.call(args).is_error)


class StdioServerTest(unittest.TestCase):
    def server(self):
        skills = library(self, plan="Present the plan before an edit")
        return StdioServer("harness", "0.1", [Find(skills, table()), Guide(skills, table()), Run(table())])

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

    def test_serve_reads_lines_and_answers_lines(self):
        out = io.StringIO()
        self.server().serve(io.StringIO('{"jsonrpc":"2.0","id":7,"method":"ping"}\nnot json\n\n'), out)
        first, second = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual((first["id"], second["error"]["code"]), (7, -32700))


if __name__ == "__main__":
    unittest.main()
