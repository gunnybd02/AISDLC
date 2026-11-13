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

    def test_a_block_or_an_action_added_twice_is_refused(self):
        t = table()
        with self.assertRaises(ValueError):
            t.add_block("health", "again")
        with self.assertRaises(ValueError):
            t.add("health", "echo", "again", {}, lambda: "")


class SkillsTest(unittest.TestCase):
    def test_the_library_reads_name_description_and_text(self):
        skill = library(self, plan="Present the plan before an edit").get("plan")
        self.assertEqual((skill.name, skill.description), ("plan", "Present the plan before an edit"))
        self.assertIn("The body of plan.", skill.text)

    def test_a_skill_without_frontmatter_or_with_an_empty_name_is_refused(self):
        # with \s* the empty name would swallow the next line and read as "foo: bar"
        for text in ("# no frontmatter\n", "---\ndescription: d\nname:\nfoo: bar\n---\n"):
            with self.subTest(text=text), self.assertRaises(SkillError):
                Skills.read(tree(self, {"bad/SKILL.md": text}) / "bad" / "SKILL.md")

    def test_a_bad_skill_hides_no_good_one(self):
        root = tree(self, {"bad/SKILL.md": "# none\n", "plan/SKILL.md": SKILL.format(name="plan", about="x")})
        (root / "latin").mkdir()
        (root / "latin" / "SKILL.md").write_bytes(b"---\nname: latin\ndescription: \xe9\n---\n")
        lib = Skills(root)
        self.assertEqual([s.name for s in lib.all()], ["plan"])
        self.assertIn("latin/SKILL.md", " ".join(lib.problems()))

    def test_the_library_lists_its_problems(self):
        lib = Skills(tree(self, {"bad/SKILL.md": "# none\n", "a/SKILL.md": SKILL.format(name="b", about="x"),
                                 "b/SKILL.md": SKILL.format(name="b", about="y")}))
        found = " ".join(lib.problems())
        self.assertIn("bad/SKILL.md", found)
        self.assertIn("folder a", found)
        self.assertIn("twice", found)
        self.assertEqual(library(self, plan="x").problems(), [])

    def test_a_bom_and_a_frontmatter_at_the_end_of_the_file_read(self):
        lib = Skills(tree(self, {"a/SKILL.md": "﻿---\nname: a\ndescription: d\n---"}))
        self.assertEqual(lib.get("a").description, "d")


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
