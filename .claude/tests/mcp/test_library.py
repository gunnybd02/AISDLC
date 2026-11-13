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


if __name__ == "__main__":
    unittest.main()
