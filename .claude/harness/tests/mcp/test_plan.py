"""h7.approval: the plan block keeps a plan as data, checked by the desk; revisions change only the given items; a
waiting plan can be shown, read and dropped; a plan without a session, or with problems, is not kept. The answers
follow docs 04 sections 8 and 10: the head line, the form, the overview of a plan with no code, the block in a fence;
a revision shows only its changed lines."""
import os
import re
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.utils.contracts import YES
from harness.utils.plan.approval import approvals
from harness.tests.e2e import copy_tree
from harness.tests.mcp import caller

OVERVIEW = {"problem": ["no greeting"], "need": ["greet the user"], "how": ["a function"], "accept": ["hello shows"]}
PLAN = {"title": "Add a greeting", "what": ["say hello"], "files": ["hello.py"], "tests": ["test_hello.py"]}


class PlanBlockTest(unittest.TestCase):
    def setUp(self):
        self.root = copy_tree(self)  # the writes of the plan block meet the real judge of this tree
        self.port = LedgerPort(self.root)
        self.port.touch_session("s1")
        self.run = caller(self.root)

    def call(self, name, **args):
        result = self.run("plan", name, **args)
        if result.is_error:
            raise ValueError(result.text)
        return result.text

    def present(self, plan=None):
        out = self.call("plan_present", plan=plan or {**PLAN, "overview": OVERVIEW})
        return re.search(r"plan (pd-[0-9a-z]+-[0-9a-f]{6}) rev", out).group(1), out

    def test_plan_present_keeps_the_plan_and_gives_the_block_and_the_form(self):
        plan_id, out = self.present()
        head, ask, overview, block = out.split("\n\n")
        sha = self.port.revision(plan_id)["sha"]
        self.assertTrue(head.startswith(f'"Add a greeting": plan {plan_id} rev 1 is waiting for the user\'s approval '
                                        f"(sha {sha[:8]}): 2 files, 0 steps, 0 behaviours. Only the user's \"{YES}\""))
        self.assertIn("do not repeat it", ask)
        self.assertEqual(overview, "Problem: no greeting\nNeed: greet the user\nHow: a function\nAccept: hello shows")  # a plan with no code: its overview above the block
        self.assertEqual(block, "```text\n## Plan\nServices: agent-code\nWhat: say hello\nFiles: hello.py\n"
                                "Tests: test_hello.py\n```")
        root = self.port.revision(plan_id)["items"]["root"]
        self.assertEqual(root, os.getcwd().replace("\\", "/"))  # the root is the MCP server's folder, kept, not shown
        self.assertIn(f'exactly: {YES} plan "Add a greeting" ({plan_id} rev 1)? Header', out)
        waiting = self.port.waiting()
        self.assertEqual([(w["plan_id"], w["sid"], w["items"]["services"]) for w in waiting], [(plan_id, "s1", ["agent-code"])])

    def test_a_plan_with_problems_is_not_kept(self):
        for plan, why in (({**PLAN, "title": "x"}, "title"), ({k: v for k, v in PLAN.items() if k != "what"}, "what"),
                          ({**PLAN, "files": []}, "files"), ({**PLAN, "files": ["/abs.py"]}, "not a path inside"),
                          ({**PLAN, "files": ["../out.py"]}, "not a path inside"), ({**PLAN, "extra": 1}, "unknown item"),
                          ({**PLAN, "files": [".git/hooks/pre-commit"]}, ".git"),
                          ({**PLAN, "title": 'say "hi" now'}, "double quote"), ({**PLAN, "title": "pd-abc-123456"}, "title"),
                          ({**PLAN, "files": ["~/a.py"]}, "not a path inside"), ({**PLAN, "files": ["a.py, b.py"]}, "comma"),
                          ({**PLAN, "services": ["billing"]}, "no declared unit"),
                          ({**PLAN, "what": ["x" * 201]}, "200"), ({**PLAN, "commands": ["rm -rf /"]}, "twg line")):
            with self.subTest(why=why):
                with self.assertRaises(ValueError) as caught:
                    self.call("plan_present", plan=plan)
                self.assertIn("not kept", str(caught.exception))
                self.assertIn(why, str(caught.exception))
        self.assertEqual(self.port.waiting(), [])

    def test_a_full_plan_needs_its_items(self):
        steps = [{"commit": "Add the parser", "points": ["parse the line"], "files": ["parse.py"],
                  "tests": ["test_parse.py"], "behaviors": [{"id": "reads", "what": "reads a line", "how": "unit test",
                                                             "why": "the gate needs it"}]}]
        with self.assertRaises(ValueError) as caught:
            self.call("plan_present", plan={**PLAN, "steps": steps})
        for item in ("services", "checks", "assumptions", "notDoing", "risks", "overview", "code"):
            self.assertIn(item, str(caught.exception))
        full = {**PLAN, "steps": steps, "services": ["agent-code"], "checks": ["the suite passes"],
                "assumptions": ["python 3"], "notDoing": ["no cli"], "risks": ["none known"],
                "overview": {"problem": ["p"], "need": ["n"], "how": ["h"], "accept": ["a"]},
                "code": [{"file": "parse.py", "code": "def parse(line): ...", "reason": "the parser"}]}
        plan_id, out = self.present(full)
        self.assertIn("4 files, 1 steps, 1 behaviours", out)
        self.assertNotIn("Problem: p\n\n", out)  # a plan with code: its overview is in the block
        self.assertIn("## Plan\nProblem: p\nNeed: n\nHow: h\nAccept: a\nCode:\n- parse.py: def parse(line): ... | "
                      "why: the parser\nServices: agent-code\nWhat: Add a greeting\n", out)
        self.assertIn("- s1.reads: reads a line | how: unit test | why: the gate needs it", out)
        self.assertIn("1. Add the parser | parse.py | test_parse.py | parse the line", out)

    def test_a_revision_changes_only_the_given_items(self):
        plan_id, _ = self.present()
        out = self.call("plan_revise", plan=plan_id, changes={"files": ["hello.py", "README.md"]}, why={"files": "docs"})
        self.assertIn(f"plan {plan_id} rev 2 is waiting", out)
        self.assertIn("A chat word approves nothing. Changed: files.", out)
        self.assertTrue(out.endswith("```text\nFiles: hello.py, README.md\n```"))  # only the changed lines
        newest = self.port.revision(plan_id)
        self.assertEqual((newest["rev"], newest["items"]["files"], newest["items"]["what"]),
                         (2, ["hello.py", "README.md"], ["say hello"]))
        for changes, why in (({}, "nothing changed"), ({"files": ["hello.py", "README.md"]}, "nothing changed"),
                             ({"bogus": 1}, "unknown item"), ({"files": ["/x.py"]}, "not a path inside")):
            with self.subTest(why=why), self.assertRaises(ValueError) as caught:
                self.call("plan_revise", plan=plan_id, changes=changes)
            self.assertIn(why, str(caught.exception))
        with self.assertRaises(ValueError):
            self.call("plan_revise", plan="pd-nothere-000000", changes={"what": ["x y"]})

    def test_a_running_plan_takes_no_revision_of_record_items_or_files(self):
        plan_id, _ = self.present()
        approvals(self.port, "s1", {self.port.waiting()[0]["question"]: YES})
        with self.assertRaises(ValueError) as caught:
            self.call("plan_revise", plan=plan_id, changes={"files": ["other.py"]})
        self.assertIn("add file", str(caught.exception))
        self.assertIn("rev 2", self.call("plan_revise", plan=plan_id, changes={"what": ["say hello and bye"]}))

    def test_a_new_plan_replaces_the_plan_that_waited_in_the_same_session(self):
        first, _ = self.present()
        other, _, _ = self.port.present({**PLAN, "root": "/r"}, sid="s2")  # another session's plan stays
        second, _ = self.present({**PLAN, "title": "Add a farewell", "overview": OVERVIEW})
        self.assertEqual(sorted(w["plan_id"] for w in self.port.waiting()), sorted([other, second]))
        self.assertEqual(self.port.revision(first)["event"], "dropped")  # its form no longer counts
        revised = self.call("plan_revise", plan=second, changes={"what": ["say bye"]})
        self.assertIn("rev 2 is waiting", revised)  # a revision replaces nothing
        self.assertEqual(sorted(w["plan_id"] for w in self.port.waiting()), sorted([other, second]))

    def test_a_revision_shows_the_overview_only_when_it_changed(self):
        plan_id, _ = self.present()
        files = self.call("plan_revise", plan=plan_id, changes={"files": ["hello.py", "README.md"]})
        self.assertNotIn("Problem: no greeting", files)
        changed = self.call("plan_revise", plan=plan_id, changes={"overview": {**OVERVIEW, "need": ["greet and wave"]}})
        self.assertIn("Problem: no greeting\nNeed: greet and wave", changed)

    def test_show_status_and_drop(self):
        plan_id, _ = self.present()
        shown = self.call("plan_show")
        self.assertIn("## Plan\nServices: agent-code\nWhat: say hello\n", shown)
        self.assertIn(f'exactly: {YES} plan "Add a greeting" ({plan_id} rev 1)?', shown)  # it waits: the form again
        approvals(self.port, "s1", {self.port.waiting()[0]["question"]: "do it another way"})
        status = self.call("plan_status", plan=plan_id)
        self.assertIn("rev 1", status)
        self.assertIn("waiting", status)
        self.assertIn("1 feedback not answered\n- do it another way", status)
        self.assertIn("1 revision(s) stay", self.call("plan_drop", plan=plan_id))
        self.assertEqual(self.port.waiting(), [])
        self.assertIn("not waiting (dropped)", self.call("plan_status", plan=plan_id))
        shown = self.call("plan_show", plan=plan_id)
        self.assertIn("is dropped; it does not wait for an approval", shown)
        self.assertNotIn("AskUserQuestion", shown)  # no form for a plan that does not wait
        with self.assertRaises(ValueError):
            self.call("plan_drop", plan=plan_id)

    def test_no_session_no_plan(self):
        root = copy_tree(self)
        result = caller(root)("plan", "plan_present", plan=PLAN)
        self.assertTrue(result.is_error)
        self.assertIn("no session", result.text)


class PlanStatusTest(unittest.TestCase):
    def test_status_shows_the_ticket_of_the_calling_session(self):
        root = copy_tree(self)
        port = LedgerPort(root)
        run = caller(root)
        port.touch_session("s1")
        self.assertIn("no ticket (phase prepare)", run("plan", "plan_status").text)
        plan_id, _, q = port.present({**PLAN, "root": str(root)}, sid="s1")
        approvals(port, "s1", {q: YES})
        out = run("plan", "plan_status").text
        self.assertIn(f"open, phase execute, plan {plan_id}", out)
        self.assertIn("approved", out)
        self.assertIn("0 feedback not answered", out)  # found live: the approval word counted as feedback


if __name__ == "__main__":
    unittest.main()
