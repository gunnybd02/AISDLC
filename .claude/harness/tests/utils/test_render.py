"""The plan block as the user reads it (docs 04 sections 7.3, 8, 10): a bare ## Plan heading and one line per item in
a fixed order; a plan with code shows its overview and code first; a child's line holds its whole card; a revision
shows only its changed lines."""
import unittest

from harness.utils.plan import render

LIGHT = {"title": "Add a greeting", "services": ["agent-code"], "branch": "feat/hello", "what": ["say hello", "say bye"],
         "files": ["hello.py", "bye.py"], "tests": ["test_hello.py"], "commit": "Add a greeting",
         "root": "/somewhere/else", "overview": {"problem": ["p"], "need": ["n"], "how": ["h"], "accept": ["a"]}}
FULL = {**LIGHT, "checks": ["the suite passes"], "assumptions": ["python 3"], "notDoing": ["no cli"],
        "risks": ["none known", "slow"], "network": [{"host": "example.com", "port": 443, "why": "the api"}],
        "commands": ["twg issue view ABC-1"], "teamSkills": ["style", "review"],
        "code": [{"file": "hello.py", "code": "def hello(name):\n    return name", "reason": "the greeting"}],
        "steps": [{"commit": "Add hello", "files": ["hello.py"], "tests": ["test_hello.py"], "points": ["greet", "test"]}],
        "behaviors": [{"id": "s1.greets", "what": "greets by name", "how": "unit test", "why": "the user sees it"}]}
CARD = {"name": "echo", "unit": "sandbox", "goal": "Add echo(text, times)", "ac": ["echo('ab', 3) returns 'ababab'",
                                                                                 "times below one raises ValueError"],
        "change": ["play/echo.py"], "tests": ["play/test_echo.py"], "actions": ["push"]}


class BlockTest(unittest.TestCase):
    def test_the_block_starts_with_plan_and_holds_one_line_per_item_in_order(self):
        self.assertEqual(render.block(LIGHT).splitlines(), [
            "## Plan", "Services: agent-code", "Branch: feat/hello", "What: say hello; say bye",
            "Files: hello.py, bye.py", "Tests: test_hello.py", "Commit: Add a greeting"])
        self.assertNotIn("/somewhere/else", render.block(LIGHT))  # no Root line: the server sets the root
        labels = [text.split(":")[0] for text in render.block(FULL).splitlines()[1:] if not text[0] in "-1"]
        self.assertEqual(labels, ["Problem", "Need", "How", "Accept", "Code", "Services", "Branch", "What", "Files",
                                  "Tests", "Checks", "Commit", "Behaviors", "Network", "Commands", "Team skills",
                                  "Assumptions", "Not doing", "Risks"])
        lines = render.block(FULL).splitlines()
        self.assertIn("1. Add hello | hello.py | test_hello.py | greet; test", lines)
        self.assertIn("- s1.greets: greets by name | how: unit test | why: the user sees it", lines)
        self.assertIn("Network: example.com:443 (the api)", lines)
        self.assertIn("Risks: none known; slow", lines)
        self.assertIn("Team skills: style, review", lines)

    def test_a_plan_with_code_shows_overview_and_code_first_and_its_what_is_the_title(self):
        lines = render.block(FULL).splitlines()
        self.assertEqual(lines[1:7], ["Problem: p", "Need: n", "How: h", "Accept: a", "Code:",
                                      "- hello.py: def hello(name): return name | why: the greeting"])
        self.assertIn("What: Add a greeting", lines)
        self.assertNotIn("Problem: p", render.block(LIGHT))  # no code: the answer prints the overview above the block
        self.assertEqual(render.overview_lines(LIGHT), ["Problem: p", "Need: n", "How: h", "Accept: a"])
        empty = {**FULL, "code": [{"file": "hello.py", "code": "", "reason": "named by the parent"}]}
        self.assertIn("- hello.py | why: named by the parent", render.block(empty).splitlines())

    def test_a_childs_line_holds_its_whole_card(self):
        plan = {**LIGHT, "children": [CARD]}
        self.assertEqual(render.block(plan).splitlines()[-2:], [
            "Children:", "- echo (sandbox): Add echo(text, times) | AC: echo('ab', 3) returns 'ababab'; times below "
                         "one raises ValueError | change: play/echo.py | tests: play/test_echo.py | actions: push"])
        other = {**LIGHT, "children": [{**CARD, "ac": [CARD["ac"][0], "times below one returns ''"]}]}
        self.assertNotEqual(render.sha(render.block(plan)), render.sha(render.block(other)))  # a criterion is approved

    def test_the_head_line_and_the_changed_lines_of_a_revision(self):
        head = render.head(FULL, "pd-x-000000", 2, ["files", "risks"])
        self.assertTrue(head.startswith('"Add a greeting": plan pd-x-000000 rev 2 is waiting for the user\'s approval '
                                        f"(sha {render.sha(render.block(FULL))[:8]}): 3 files, 1 steps, 1 behaviours."))
        self.assertTrue(head.endswith("A chat word approves nothing. Changed: files, risks."))
        new = {**FULL, "risks": ["none known"], "network": [], "steps": [{**FULL["steps"][0], "commit": "Add hello now"}]}
        self.assertEqual(render.changed(FULL, new).splitlines(), [
            "Commit:", "1. Add hello now | hello.py | test_hello.py | greet; test", "Risks: none known",
            "Removed: Network"])
        self.assertEqual(render.changed(FULL, FULL), "")
        self.assertEqual(render.fenced("## Plan"), "```text\n## Plan\n```")


if __name__ == "__main__":
    unittest.main()
