"""h7.desk: clean keeps the known items in shape, normalize fills what follows, merge applies a revision, tier says
light or full."""
import unittest

from harness.utils.plan import desk


class DeskTest(unittest.TestCase):
    def test_clean_keeps_known_items_in_one_line_deduped(self):
        out = desk.clean({"title": " Add\n a  greeting ", "commit": "Fix `x` *now* | ok", "files": ["a.py", " a.py ", ""],
                          "what": "one point", "other": 1})
        self.assertEqual(out, {"title": "Add a greeting", "commit": "Fix x now ok", "files": ["a.py"], "what": ["one point"]})

    def test_normalize_fills_behaviours_files_tests_and_light_services(self):
        items = desk.normalize(desk.clean({
            "title": "Ship it now", "files": ["a.py"], "overview": {"problem": "p", "need": "n", "how": "h", "accept": "ok"},
            "steps": [{"commit": "c", "points": ["p"], "files": ["s.py"], "tests": ["t_s.py"],
                       "behaviors": [{"id": "one", "what": "w", "how": "h", "why": "y"}]}],
            "code": [{"file": "c.py", "code": "x", "reason": "r"}],
            "test": [{"file": "t_c.py", "name": "two", "expects": "e", "how": "h", "why": ""}]}))
        self.assertEqual(items["files"], ["a.py", "s.py", "c.py"])
        self.assertEqual(items["tests"], ["t_s.py", "t_c.py"])
        self.assertEqual([(b["id"], b.get("step")) for b in items["behaviors"]], [("s1.one", 1), ("two", None)])
        self.assertEqual(items["behaviors"][1]["why"], "ok")
        self.assertEqual(desk.tier(items), "full")
        self.assertNotIn("services", items)
        self.assertEqual(desk.normalize({"files": ["a.py"]})["services"], ["agent-code"])

    def test_merge_replaces_given_items_and_new_files_join_the_last_step(self):
        old = {"files": ["a.py"], "what": ["w"], "steps": [{"commit": "c", "points": ["p"], "files": ["a.py"]}]}
        out = desk.merge(old, {"files": ["a.py", "b.py"]})
        self.assertEqual((out["files"], out["what"], out["steps"][-1]["files"]), (["a.py", "b.py"], ["w"], ["a.py", "b.py"]))
        self.assertEqual(old["steps"][0]["files"], ["a.py"])

    def test_a_step_behaviour_must_sit_in_its_step(self):
        self.assertIn("its step is 2", " ".join(desk.behaviors_problems([{"id": "s2.x", "what": "w", "how": "h",
                                                                          "why": "y", "step": 1}])))

    def test_network_children_and_ids(self):
        self.assertTrue(desk.network_problems([{"host": "https://x.com", "port": 443, "why": "w"}]))
        self.assertEqual(desk.network_problems([{"host": "api.x.com", "port": 443, "why": "w"}]), [])
        good = {"name": "api", "unit": "agent-code", "goal": "g", "ac": ["returns the list", "keeps the order"]}
        self.assertEqual(desk.CHECKS["children"]([good], ()), [])
        self.assertTrue(desk.CHECKS["children"]([{**good, "actions": ["merge"]}], ()))
        self.assertRegex(desk.new_id(), r"^pd-[0-9a-z]+-[0-9a-f]{6}$")


class RevisedBehavioursTest(unittest.TestCase):
    def test_a_replaced_test_or_steps_item_takes_the_behaviours_it_made_with_it(self):
        def test(name):
            return {"file": "t.py", "name": name, "expects": "e", "how": "h", "why": "w"}
        own = {"id": "kept-one", "what": "w", "how": "h", "why": "y"}
        old = desk.normalize(desk.clean({"title": "A plan here", "what": ["w"], "files": ["a.py"], "behaviors": [own],
                                         "test": [test("old-one"), test("old-two")],
                                         "steps": [{"commit": "c", "points": ["p"], "files": ["a.py"],
                                                    "behaviors": [{"id": "made", "what": "w", "how": "h", "why": "y"}]}]}))
        ids = lambda items: sorted(b["id"] for b in items["behaviors"])
        self.assertEqual(ids(old), ["kept-one", "old-one", "old-two", "s1.made"])
        new = desk.normalize(desk.merge(old, desk.clean({"test": [test("s1.new-one")]})))
        self.assertEqual(ids(new), ["kept-one", "s1.made", "s1.new-one"])  # the old test names are gone
        steps = desk.normalize(desk.merge(old, desk.clean({"steps": [{"commit": "c", "points": ["p"], "files": ["a.py"]}]})))
        self.assertEqual(ids(steps), ["kept-one", "old-one", "old-two"])  # the old step's behaviour is gone
        given = desk.normalize(desk.merge(old, desk.clean({"test": [test("x")], "behaviors": [own]})))
        self.assertEqual(ids(given), ["kept-one", "s1.made", "x"])  # a behaviors item given replaces the list whole;
        # the steps are not replaced, so their behaviour comes back from them


if __name__ == "__main__":
    unittest.main()
