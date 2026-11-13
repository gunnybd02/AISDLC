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


if __name__ == "__main__":
    unittest.main()
