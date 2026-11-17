"""orchestra part 2: a brief as a session's first prompt makes it a child (never a later prompt, never a brief whose
parts disagree); the card plan made from the card; a child never presents or closes a plan, nor asks for the maint
grant."""
import json
import unittest

from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.mcp.actions.maint import Grant
from harness.mcp.actions.plan import PlanPresent
from harness.mcp.actions.steps import PlanClose
from harness.utils.contracts import ActionContext, ActionError, Event, Verdict
from harness.utils.orchestra import brief, child
from harness.tests.e2e import copy_tree

CARD = {"name": "api", "unit": "home", "goal": "List the orders of a user",
        "ac": ["GET /orders returns the user's orders", "an unknown user gets 404"],
        "change": ["app/orders.py"], "tests": ["tests/test_orders.py"]}
BRIEF = brief.brief(7, "pd-x", CARD, "session_parent01", rounds=3)


class ChildTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(copy_tree(self, {"project.json": json.dumps({"name": "t"})}))

    def prompt(self, sid, text):
        return Act(self.port).run(Event("UserPromptSubmit", "", {"prompt": text}, sid, "/w"), {}, Verdict("allow"))

    def test_the_first_prompt_that_is_a_brief_makes_a_child(self):
        notes = self.prompt("c1", BRIEF)
        self.assertIn("child api of the delegated plan 7", " ".join(notes))
        role = child.role_of(self.port.ticket("c1"))
        self.assertEqual((role["name"], role["plan"], role["parent"], role["branch"], role["behaviours"]),
                         ("api", 7, "session_parent01", "orch/p7/api", ["p7.api.ac1", "p7.api.ac2"]))
        self.prompt("c1", BRIEF.replace('"api"', '"web"'))  # a later brief changes nothing
        self.assertEqual(child.role_of(self.port.ticket("c1"))["name"], "api")

    def test_a_later_prompt_or_a_brief_that_disagrees_makes_no_child(self):
        self.prompt("s2", "hello")
        self.prompt("s2", BRIEF)  # a message from another session comes later than the first prompt
        self.assertIsNone(child.role_of(self.port.ticket("s2")))
        self.assertIsNone(child.parse(BRIEF.replace('"orch/p7/api"', '"orch/p8/api"')))
        self.assertIsNone(child.parse(BRIEF.replace("of the delegated plan 7", "of the delegated plan 9")))
        self.assertIsNone(child.parse(BRIEF.split(brief.CARD_OPEN)[0]))

    def test_the_card_plan(self):
        items = child.card_plan(child.parse(BRIEF), "/repo")
        self.assertEqual((items["title"], items["files"], items["tests"], items["services"], items["branch"],
                          items["root"]), ("api: List the orders of a user", ["app/orders.py"],
                                           ["tests/test_orders.py"], ["agent-code"], "orch/p7/api", "/repo"))
        self.assertEqual([(b["id"], b["what"], b["test"]) for b in items["behaviors"]],
                         [("p7.api.ac1", "AC1: GET /orders returns the user's orders", "tests/test_orders.py"),
                          ("p7.api.ac2", "AC2: an unknown user gets 404", "tests/test_orders.py")])
        self.assertEqual(items["steps"][0]["commit"], "List the orders of a user")

    def test_a_child_never_presents_or_closes_a_plan_nor_asks_for_the_grant(self):
        self.prompt("c1", BRIEF)
        ctx = ActionContext({"plans": self.port, "session": lambda: "c1", "limits": lambda: {"children": 3, "rounds": 3}})
        with self.assertRaisesRegex(ActionError, "never presents a plan of its own"):
            PlanPresent().run(ctx, {"plan": {"title": "Other work", "what": ["w"], "files": ["x.py"]}})
        with self.assertRaisesRegex(ActionError, "never closes its plan"):
            PlanClose().run(ctx, {})
        with self.assertRaisesRegex(ActionError, "never asks to turn the guards off"):
            Grant().run(ctx, {"minutes": 5, "why": "w"})
        other = ActionContext({"plans": self.port, "session": lambda: "s9", "limits": lambda: {"children": 3, "rounds": 3}})
        self.assertIn("Turn guards off", Grant().run(other, {"minutes": 5, "why": "w"}))


if __name__ == "__main__":
    unittest.main()
