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


if __name__ == "__main__":
    unittest.main()
