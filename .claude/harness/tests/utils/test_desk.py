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
        self.assertEqual(desk.children_problems([good]), [])
        self.assertTrue(desk.children_problems([{**good, "actions": ["merge"]}]))
        self.assertRegex(desk.new_id(), r"^pd-[0-9a-z]+-[0-9a-f]{6}$")


if __name__ == "__main__":
    unittest.main()
