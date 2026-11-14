"""h3.three-tools: the action table, the skill library, find, guide, run and the JSON-RPC server, each on its own."""
import io
import json
import unittest

from harness.mcp.actions.table import ActionTable, args_problem, signature
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


class ActionTableTest(unittest.TestCase):
    def test_an_action_checks_its_arguments(self):
        self.assertEqual(args_problem(Echo, {"word": "hi"}), "")
        self.assertIn("word", args_problem(Echo, {}))
        self.assertIn("string", args_problem(Echo, {"word": 3}))
        self.assertIn("other", args_problem(Echo, {"word": "hi", "other": 1}))
        self.assertIn("object", args_problem(Echo, ["hi"]))

    def test_an_action_shows_its_signature(self):
        self.assertEqual(signature(Echo), "echo(word: string, loud?: boolean)")

    def test_a_block_is_the_prefix_of_its_actions(self):
        t = table()
        self.assertEqual((t.blocks, t.about("health"), t.action("health", "echo")), (["health"], "Say a word back", Echo))
        with self.assertRaises(KeyError):
            t.action("nowhere", "echo")

    def test_an_action_added_twice_is_refused(self):
        with self.assertRaises(ValueError):
            table().add(Echo)


if __name__ == "__main__":
    unittest.main()
