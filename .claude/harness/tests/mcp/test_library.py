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

    def test_the_skills_of_the_harness_are_whole_workflows(self):
        lib = Skills(CLAUDE_DIR / "harness" / "mcp" / "skill_docs")
        self.assertEqual(lib.problems(), [])
        self.assertEqual([s.name for s in lib.all()], ["harness-dev", "orchestrate", "refused", "store", "work"])
        work, dev = lib.get("work").text, lib.get("harness-dev").text
        for part in ("## 1. Gather context", "## 2. Plan", "## 3. Build each step", "## 4. Ship", "## 5. Close",
                     'guide("refused", "skills")', 'guide("harness-dev", "skills")', 'guide("store", "skills")'):
            self.assertIn(part, work)
        for part in ("## 1. Gather context", "## 2. Plan", "## 3. Build", "## 4. Check", "## 5. Pull request",
                     "## 6. Release", 'guide("work", "skills")'):
            self.assertIn(part, dev)

    def test_the_skills_name_every_place_code_the_check_after_and_the_verify_door(self):
        """s8.docs.auto: the refused skill names every code of the place rules (the check after among them); work and
        harness-dev name the check after (auto mode) and the verify door for tests."""
        lib = Skills(CLAUDE_DIR / "harness" / "mcp" / "skill_docs")
        rows = json.loads((CLAUDE_DIR / "harness" / "gear" / "rules" / "place.json").read_text(encoding="utf-8"))
        codes = [row.get("code") or row.get("finding") for row in rows["rules"]]
        self.assertEqual([c for c in codes if c not in lib.get("refused").text], [])
        self.assertLessEqual({"shell.after", "plan.outside_after", "plan.none_after", "stop.outside"}, set(codes))
        for name in ("work", "harness-dev"):
            self.assertIn("auto mode", lib.get(name).text)
            self.assertIn("cli verify", lib.get(name).text)

    def test_the_orchestrate_skill_names_the_lock_and_the_plan_branch(self):
        """s6.docs.orchestra: the parent writes acTests, locks them, and children work on plan/p<plan>."""
        lib = Skills(CLAUDE_DIR / "harness" / "mcp" / "skill_docs")
        for name in ("orchestrate", "work"):
            text = lib.get(name).text
            for part in ("acTests", 'run("orchestra", "lock", {})', "plan/p<plan>"):
                self.assertIn(part, text, name)

    def test_the_skills_name_the_tickets_and_the_stores_folders(self):
        """s6.docs.tickets: orchestrate names orchestra.tickets after lock; store names db/ and tickets/."""
        lib = Skills(CLAUDE_DIR / "harness" / "mcp" / "skill_docs")
        orchestrate, store_text = lib.get("orchestrate").text, lib.get("store").text
        self.assertIn('run("orchestra", "tickets", {})', orchestrate)
        self.assertLess(orchestrate.index('run("orchestra", "lock", {})'), orchestrate.index('run("orchestra", "tickets"'))
        for part in ("`db/`", "`tickets/`", "the `db` folder's id"):
            self.assertIn(part, store_text)

    def test_the_store_skill_says_copies_are_gzipped(self):
        """s2.docs.gzip: a person can open a copy."""
        text = Skills(CLAUDE_DIR / "harness" / "mcp" / "skill_docs").get("store").text
        for part in (".db.gz", "application/gzip", "gunzip <name>.db.gz"):
            self.assertIn(part, text)

    def test_a_request_in_plain_words_finds_its_skill_first(self):
        find = Find(Skills(CLAUDE_DIR / "harness" / "mcp" / "skill_docs"), ActionTable())
        for words, name in (("where do I start in this session", "work"),
                            ("write and present a plan for approval", "work"),
                            ("verify the tests and end the step with step_done", "work"),
                            ("push the branch and open a merge request", "work"),
                            ("close the plan", "work"),
                            ("my tool call was refused or denied", "refused"),
                            ("upload the ledger database to google drive", "store"),
                            ("back up the session database when a plan closes", "store"),
                            ("which session and when is a stored copy from", "store"),
                            ("develop the harness itself", "harness-dev"),
                            ("add a rule with a detector", "harness-dev"),
                            ("add an action or a skill to the harness", "harness-dev"),
                            ("publish a release and update sessions", "harness-dev")):
            with self.subTest(words=words):
                first = find.call({"query": words, "mode": "skills"}).text.splitlines()[0]
                self.assertTrue(first.startswith(f"[skills] {name} "), first)

    def test_a_bom_and_a_frontmatter_at_the_end_of_the_file_read(self):
        lib = Skills(tree(self, {"a/SKILL.md": "﻿---\nname: a\ndescription: d\n---"}))
        self.assertEqual(lib.get("a").description, "d")


if __name__ == "__main__":
    unittest.main()
