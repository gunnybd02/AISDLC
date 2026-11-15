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
from harness.tests import CLAUDE_DIR, tree

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

    def test_a_skill_that_names_what_is_not_there_is_stale(self):
        body = ('run("plan", "step_done", {}) and run(\'plan\', \'gone\', {}); guide("plan", "mcp"), guide("git", "mcp"); '
                'guide("a", "skills"), guide("lost-one", "skills"); run("<block>", "<action>") is a frame, not a call')
        lib = Skills(tree(self, {"a/SKILL.md": SKILL.format(name="a", about="x") + body}))
        self.assertEqual(lib.stale(["plan.step_done", "plan.plan_show"]), [
            "skill a: names the action plan.gone, which is not there",
            "skill a: names the block git, which is not there",
            "skill a: names the skill lost-one, which is not there"])
        self.assertEqual(library(self, plan="x").stale([]), [])

    def test_the_skills_of_the_harness_read_and_start_lists_each(self):
        lib = Skills(CLAUDE_DIR / "harness" / "mcp" / "skill_docs")
        self.assertEqual(lib.problems(), [])
        names = [s.name for s in lib.all()]
        self.assertEqual(names, ["close", "harness-action", "harness-map", "harness-release", "harness-rule",
                                 "harness-skill", "plan", "refused", "ship", "start", "step"])
        start = lib.get("start").text
        for name in names:
            with self.subTest(skill=name):
                self.assertTrue(name == "start" or f"| `{name}` |" in start, f"start does not list {name}")
                self.assertIn("\n## ", lib.get(name).text)  # the frame: a title and sections

    def test_a_request_in_plain_words_finds_its_skill_first(self):
        find = Find(Skills(CLAUDE_DIR / "harness" / "mcp" / "skill_docs"), ActionTable())
        for words, name in (("how do I start working in this session", "start"),
                            ("write and present a plan for approval", "plan"),
                            ("verify the tests and end the step with step_done", "step"),
                            ("push the branch and open a merge request", "ship"),
                            ("close the plan as delivered", "close"),
                            ("my tool call was refused or denied", "refused"),
                            ("where are the folders of the harness", "harness-map"),
                            ("add a rule with a detector and a rule row", "harness-rule"),
                            ("add an action to a tool block", "harness-action"),
                            ("write a skill text", "harness-skill"),
                            ("publish a release and update a running session", "harness-release")):
            with self.subTest(words=words):
                first = find.call({"query": words, "mode": "skills"}).text.splitlines()[0]
                self.assertTrue(first.startswith(f"[skills] {name} "), first)

    def test_a_bom_and_a_frontmatter_at_the_end_of_the_file_read(self):
        lib = Skills(tree(self, {"a/SKILL.md": "﻿---\nname: a\ndescription: d\n---"}))
        self.assertEqual(lib.get("a").description, "d")


if __name__ == "__main__":
    unittest.main()
