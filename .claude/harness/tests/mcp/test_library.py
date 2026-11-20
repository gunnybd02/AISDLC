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

    def test_the_orchestrate_skill_names_the_lock_and_the_parents_own_copy(self):
        """s6.docs.orchestra: the parent writes acTests, locks them, and runs its own copy at check."""
        lib = Skills(CLAUDE_DIR / "harness" / "mcp" / "skill_docs")
        for name in ("orchestrate", "work"):
            text = lib.get(name).text
            for part in ("acTests", 'run("orchestra", "lock", {})', "own copy"):
                self.assertIn(part, text, name)

    def test_the_skills_name_the_tickets_and_the_stores_folders(self):
        """s6.docs.tickets: orchestrate names orchestra.tickets after lock; store names db/ and tickets/."""
        lib = Skills(CLAUDE_DIR / "harness" / "mcp" / "skill_docs")
        orchestrate, store_text = lib.get("orchestrate").text, lib.get("store").text
        self.assertIn('run("orchestra", "tickets", {})', orchestrate)
        self.assertLess(orchestrate.index('run("orchestra", "lock", {})'), orchestrate.index('run("orchestra", "tickets"'))
        for part in ("`db/`", "`tickets/`", "the `db` folder's id"):
            self.assertIn(part, store_text)

    def test_the_work_skill_says_a_child_registers_at_take(self):
        """s4.docs.register: what a child does at take, and when it is refused."""
        lib = Skills(CLAUDE_DIR / "harness" / "mcp" / "skill_docs")
        work = lib.get("work").text
        for part in ("take registers you before any", "keeps no copy", "Registration failed", "names #N"):
            self.assertIn(part, work)
        self.assertIn("Registration failed", lib.get("orchestrate").text)

    def test_the_skills_name_the_commit_format_the_registration_commit_and_ci(self):
        """s5.docs.ci: a child reads its rules in the work skill; the parent reads the issue format in orchestrate."""
        lib = Skills(CLAUDE_DIR / "harness" / "mcp" / "skill_docs")
        work = " ".join(lib.get("work").text.split())
        for part in ("it starts `#N <name>: `", "registration as a comment on your issue",
                     "Your merge request goes into main"):
            self.assertIn(part, work)
        orchestrate = " ".join(lib.get("orchestrate").text.split())
        for part in ("harness-issue/1", "`[p<plan>] <name>: <goal>`", "CI is the project's own"):
            self.assertIn(part, orchestrate)

    def test_the_orchestrate_skill_says_ci_is_the_projects_own(self):
        """s3.docs.workflow: lock pushes nothing; the harness never adds a CI file; a plan may write one; no CI skips."""
        text = " ".join(Skills(CLAUDE_DIR / "harness" / "mcp" / "skill_docs").get("orchestrate").text.split())
        for part in ("pushes nothing (no branch, no CI file)", "The harness never adds a CI file by itself",
                     "a plan may write one", "A repository with no CI skips the CI phase"):
            self.assertIn(part, text)

    def test_the_orchestrate_skill_says_spawn_opens_a_draft_and_started_waits_for_the_watch(self):
        """s4.docs.draft: the start commit, the draft pull request, the watch call first, and started waiting."""
        text = " ".join(Skills(CLAUDE_DIR / "harness" / "mcp" / "skill_docs").get("orchestrate").text.split())
        for part in ("opens its draft pull request into the base, once", "begins with the watch call",
                     "`mcp__claude-code-remote__subscribe_pr_activity {owner, repo, pullNumber}`",
                     "started waits for it", "Accept later makes that draft ready"):
            self.assertIn(part, text)

    def test_the_skills_say_a_child_speaks_in_pr_comments_and_the_doorbell_reads_them(self):
        """s4.docs.doorbell: the orchestrate skill names the doorbell and its next steps; the work skill says question
        and handback become comments on the draft, never send_message."""
        lib = Skills(CLAUDE_DIR / "harness" / "mcp" / "skill_docs")
        orchestrate = " ".join(lib.get("orchestrate").text.split())
        for part in ('`run("orchestra", "doorbell", {})`', "A child cannot message you (auto mode refuses it)",
                     "| CI is RED after its handback, the failed checks named | `reject` with those checks |",
                     "| it handed back and CI is green, or there is no CI | `check`, then `accept` |"):
            self.assertIn(part, orchestrate)
        work = " ".join(lib.get("work").text.split())
        for part in ("the harness posts each as a comment on your draft pull request",
                     "Never `send_message` (auto mode refuses it)"):
            self.assertIn(part, work)

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


class OrdersDocsTest(unittest.TestCase):
    def test_no_text_tells_a_child_to_send_message_and_the_skills_name_orders_and_close(self):
        """s8.docs.orders: a child that sends a message is refused by auto mode; the parent sends signed orders."""
        import json
        from pathlib import Path
        from harness.tests import CLAUDE_DIR
        harness = Path(CLAUDE_DIR) / "harness"
        for name in ("actions.json", "place.json", "base.json", "git.json"):
            for row in json.loads((harness / "gear" / "rules" / name).read_text(encoding="utf-8"))["rules"]:
                code = row.get("code") or row.get("finding")
                if str(code).startswith("child."):
                    self.assertNotIn("send_message", row["why"], code)
        work = (harness / "mcp" / "skill_docs" / "work" / "SKILL.md").read_text(encoding="utf-8")
        child = work[work.index("**A child session**"):work.index("## 3. Build each step")]
        self.assertEqual(child.count("send_message"), 1)
        self.assertIn("Never `send_message` (auto mode refuses it)", child)
        self.assertIn("signed order", child)
        orchestrate = (harness / "mcp" / "skill_docs" / "orchestrate" / "SKILL.md").read_text(encoding="utf-8")
        for words in ("signed order", "signed stop order", 'run("orchestra", "close", {})'):
            self.assertIn(words, orchestrate)
        self.assertIn('run("orchestra", "close", {})', work)


class TalkDocsTest(unittest.TestCase):
    def test_the_skills_say_the_talk_is_in_comments_and_name_no_harness_path(self):
        """s6.docs.comments: the work and orchestrate skills and the cloud spec name no .harness/ file of a child."""
        from pathlib import Path
        from harness.tests import CLAUDE_DIR
        root = Path(CLAUDE_DIR)
        skills = root / "harness" / "mcp" / "skill_docs"
        work = (skills / "work" / "SKILL.md").read_text(encoding="utf-8")
        orchestrate = (skills / "orchestrate" / "SKILL.md").read_text(encoding="utf-8")
        for text in (work, orchestrate):
            for path in (".harness/notes", ".harness/register", ".harness/handback"):
                self.assertNotIn(path, text)
        self.assertIn("comments your\nharness posts on your draft", work)
        self.assertIn("handback comment", orchestrate)
        spec = (root / "docs" / "05b-orchestra-cloud.md").read_text(encoding="utf-8")
        for path in (".harness/notes", ".harness/register", ".harness/handback"):
            self.assertNotIn(path, spec)
        self.assertIn("utils/orchestra/talk.py", (root / "docs" / "system.md").read_text(encoding="utf-8"))



class IntoMainDocsTest(unittest.TestCase):
    def test_the_skills_say_a_child_merges_into_main_after_the_parents_tests(self):
        """s8.docs.into-main: the orchestrate and work skills say the child merges into main after the parent's tests
        and name no plan branch, no harness ci and no form 2."""
        lib = Skills(CLAUDE_DIR / "harness" / "mcp" / "skill_docs")
        orchestrate = " ".join(lib.get("orchestrate").text.split())
        work = " ".join(lib.get("work").text.split())
        self.assertIn("on pass accept merges it into main yourself", orchestrate)
        self.assertIn("`accept` (it merges the child into main itself)", work)
        for text in (orchestrate, work):
            for old in ("plan branch", "plan/p<plan>", "harness ci", "cli ci", "form 2", "Form 2", '"land"'):
                self.assertNotIn(old, text)


if __name__ == "__main__":
    unittest.main()
