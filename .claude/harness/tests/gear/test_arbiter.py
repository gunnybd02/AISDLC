"""h2.one-verdict-path: decide is the one judge; the strongest verdict wins and a finding no rule names asks the user."""
import json
import unittest

import harness.gear as gear_block
from harness.gear.decide.arbiter import Decide, RuleError
from harness.utils.contracts import ALLOW, ASK, REFUSE, Finding
from harness.tests import CLAUDE_DIR, tree

TEST = "harness/tests/gear/test_arbiter.py#test_a_finding_with_a_rule_takes_its_verdict"


def rules(test, *rows, name="r.json"):
    return tree(test, {name: json.dumps({"rules": list(rows)})})


def row(finding, verdict, why="because", test=TEST):
    return {"finding": finding, "verdict": verdict, "why": why, "test": test}


def when_row(code, verdict, when, why="because", test=TEST):
    return {"code": code, "verdict": verdict, "why": why, "when": when, "test": test}


class WhenRowTest(unittest.TestCase):
    def test_a_when_row_matches_the_facts_of_an_action(self):
        judge = Decide.load(CLAUDE_DIR, rules(self, when_row("git.force_push", ASK, {"sub": "push", "force": True}),
                                              when_row("git.writes", REFUSE, {"sub": ["merge", "rebase"]}),
                                              row("commit.secret", REFUSE)))
        actions = [{"sub": "push", "force": True, "detail": "git push -f"}, {"sub": "push", "force": False},
                   {"sub": "rebase", "detail": "git rebase"}, {"sub": "push", "force": 1}]  # 1 is no true
        found = judge.matched(actions)
        self.assertEqual(found, [Finding("git.force_push", "git push -f"), Finding("git.writes", "git rebase")])
        self.assertEqual(judge.matched([{"sub": "status"}]), [])  # no match, no finding
        v = judge.decide(found + [Finding("commit.secret", "a.py")])  # both kinds of row, the strongest wins
        self.assertEqual(v.decision, REFUSE)
        self.assertEqual(judge.decide(found[:1]).reason, "because (git push -f)")

    def test_a_when_row_is_checked_when_it_loads(self):
        good = when_row("git.force_push", ASK, {"force": True})
        cases = {"unknown fact": [when_row("x.y", ASK, {"forse": True})],
                 "a code twice": [good, row("git.force_push", ASK)],
                 "an empty when": [when_row("x.y", ASK, {})],
                 "a bad value": [when_row("x.y", ASK, {"force": {"a": 1}})],
                 "a missing field": [{k: v for k, v in good.items() if k != "test"}]}
        for name, rows in cases.items():
            with self.subTest(name), self.assertRaises(RuleError):
                Decide.load(CLAUDE_DIR, rules(self, *rows), vocabulary={"force", "sub"})
        self.assertEqual(len(Decide.load(CLAUDE_DIR, rules(self, good), vocabulary={"force"}).when_rows), 1)


class DecideTest(unittest.TestCase):
    def decide(self, *rows):
        return Decide.load(CLAUDE_DIR, rules(self, *rows))

    def test_no_finding_allows(self):
        self.assertEqual(self.decide().decide([]).decision, ALLOW)

    def test_a_finding_with_a_rule_takes_its_verdict(self):
        v = self.decide(row("write.state", REFUSE, "the state belongs to the harness")).decide([Finding("write.state", "x")])
        self.assertEqual(v.decision, REFUSE)
        self.assertIn("the state belongs to the harness", v.reason)

    def test_a_finding_without_a_rule_asks_the_user_and_names_it(self):
        v = self.decide().decide([Finding("net.unknown", "curl example.org")])
        self.assertEqual(v.decision, ASK)
        self.assertIn("net.unknown", v.reason)
        self.assertIn("curl example.org", v.reason)

    def test_the_strongest_verdict_wins_with_its_own_reasons(self):
        d = self.decide(row("a", ALLOW, "fine"), row("b", ASK, "check"), row("c", REFUSE, "never"))
        v = d.decide([Finding("a"), Finding("b"), Finding("c")])
        self.assertEqual((v.decision, v.reason), (REFUSE, "never"))
        self.assertEqual(d.decide([Finding("a"), Finding("b")]).decision, ASK)

    def test_a_rules_file_without_a_list_does_not_load(self):
        for text in ('{"rules": null}', '{"rules": [1]}', "[]", "{"):
            with self.subTest(text=text), self.assertRaises(RuleError):
                Decide.load(CLAUDE_DIR, tree(self, {"r.json": text}))

    def test_the_rules_are_read_from_the_tree_given(self):
        rows = {"rules": [row("a", REFUSE, test="harness/tests/test_t.py#test_a")]}
        root = tree(self, {"harness/gear/rules/r.json": json.dumps(rows), "harness/tests/test_t.py": "def test_a():\n    pass\n"})
        self.assertEqual(Decide.load(root).decide([Finding("a")]).decision, REFUSE)

    def test_a_wrong_rule_does_not_load(self):
        bad = (row("a", "maybe"), row("a", ASK, test="harness/tests/gear/test_arbiter.py#test_not_there"),
               row("a", ASK, test="harness/tests/gear/missing.py#test_x"), {"finding": "a", "verdict": ASK},
               row("a", ASK, test="harness/tests/../harness/gear/decide.py#judge"))
        for r in bad:
            with self.subTest(row=r), self.assertRaises(RuleError):
                self.decide(r)

    def test_a_finding_named_twice_does_not_load(self):
        with self.assertRaises(RuleError):
            self.decide(row("a", ASK), row("a", REFUSE))

    def test_the_real_rules_load(self):
        Decide.load(CLAUDE_DIR)

    def test_gear_declares_decide_as_its_rule(self):
        self.assertIn({"kind": "rule", "name": "decide", "ref": "harness.gear.decide.arbiter:Decide"}, gear_block.ITEMS)


if __name__ == "__main__":
    unittest.main()
