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
from harness.utils.orchestra import brief, child, orders
from harness.tests.e2e import copy_tree
from harness.tests.utils.test_draft import DraftScenario

CARD = {"name": "api", "unit": "home", "goal": "List the orders of a user",
        "ac": ["GET /orders returns the user's orders", "an unknown user gets 404"],
        "change": ["app/orders.py"], "tests": ["tests/test_orders.py"]}
BRIEF = brief.brief(7, "pd-x", CARD, "session_parent01", rounds=3)


class ChildTest(unittest.TestCase):
    def setUp(self):
        self.port = LedgerPort(copy_tree(self))

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


class OrderKeyTest(DraftScenario):
    """Part 6: each child gets its own order key at spawn, in its card block with the parent's cloud id and rounds."""

    def test_spawn_puts_a_key_of_its_own_in_the_card_block_and_the_role_reads_it(self):
        """s2.brief.order-key"""
        out = self.spawn()
        prompt = json.loads(out[out.index("\n{") + 1:])["prompt"]
        held = orders.of_role(child.parse(prompt))
        self.assertEqual(held["key"], self.port.ticket("s1")[orders.KEYS]["hello"])
        self.assertEqual((held["rounds"], set(held)), (3, {"key", "cloud", "rounds"}))
        text = brief.brief(7, "pd-x", CARD, "330e-harness", rounds=2, cloud="session_01abc", key="k" * 32)
        self.assertEqual(orders.of_role(child.parse(text)), {"key": "k" * 32, "cloud": "session_01abc", "rounds": 2})
        self.assertEqual(orders.of_role(child.parse(BRIEF)), {})  # a brief without a key: no orders

    def test_a_fresh_session_of_the_same_child_gets_the_same_key(self):
        """s2.brief.key-kept"""
        first = orders.key_for(self.port, "s1", "hello")
        self.assertEqual(orders.key_for(self.port, "s1", "hello"), first)
        self.assertNotEqual(orders.key_for(self.port, "s1", "web"), first)
        self.assertEqual(set(self.port.ticket("s1")[orders.KEYS]), {"hello", "web"})


class OrdersBriefTest(unittest.TestCase):
    def test_the_brief_names_signed_orders_and_the_wait(self):
        """s2.brief.orders: orders come signed in the notifications; after a question or the handback the child waits."""
        self.assertIn("each a signed message in your notifications", BRIEF)
        self.assertIn("an order that does not check out is ignored", BRIEF)
        self.assertIn("stop and wait: the orchestrator's answer comes as an order", BRIEF)
        self.assertIn("Then stop and wait for the orchestrator's order", BRIEF)
        self.assertNotIn("a fresh session goes on once the orchestrator has answered", BRIEF)
        self.assertNotIn("send_message", BRIEF)


class CloudIdTest(unittest.TestCase):
    """The brief names the parent's cloud session (live run 2: the child saw only the harness id)."""

    def test_a_cloud_parent_is_named_by_its_session_id_and_its_harness_id(self):
        """s3.brief.cloud-id: cse_<id> is session_<id>; the card block keeps the harness id for the receipt."""
        cloud = brief.cloud_id({brief.CLOUD: "cse_01EXL6xW2pvoe3ouq71pxrEU"})
        self.assertEqual(cloud, "session_01EXL6xW2pvoe3ouq71pxrEU")
        text = brief.brief(7, "pd-x", CARD, "330e9430-harness", rounds=3, cloud=cloud)
        self.assertIn("orchestrator session session_01EXL6xW2pvoe3ouq71pxrEU (harness id 330e9430-harness).", text)
        self.assertIn("(session session_01EXL6xW2pvoe3ouq71pxrEU (harness id 330e9430-harness))", text)
        self.assertEqual(child.parse(text)["parent"], "330e9430-harness")

    def test_without_the_cloud_the_brief_names_the_harness_id_only(self):
        """s3.brief.no-cloud: no variable, or a value that is no cloud id, changes nothing."""
        for env in ({}, {brief.CLOUD: ""}, {brief.CLOUD: "local-123"}):
            self.assertEqual(brief.cloud_id(env), "")
        self.assertEqual(brief.cloud_id({brief.CLOUD: "session_01abc"}), "session_01abc")
        self.assertEqual(brief.brief(7, "pd-x", CARD, "session_parent01", rounds=3, cloud=""), BRIEF)
        self.assertIn("orchestrator session session_parent01.", BRIEF)
        self.assertEqual(brief.brief(7, "pd-x", CARD, "session_parent01", rounds=3, cloud="session_parent01"), BRIEF)


if __name__ == "__main__":
    unittest.main()
