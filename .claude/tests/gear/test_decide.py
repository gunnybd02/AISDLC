"""h2.one-verdict-path: decide is the one judge; the strongest verdict wins and a finding no rule names asks the user."""
import json
import unittest

import harness.gear as gear_block
from harness.gear.decide import Decide, RuleError
from harness.utils.contracts import ALLOW, ASK, REFUSE, Finding
from tests import CLAUDE_DIR, tree

TEST = "tests/gear/test_decide.py#test_a_finding_with_a_rule_takes_its_verdict"


def rules(test, *rows, name="r.json"):
    return tree(test, {name: json.dumps({"rules": list(rows)})})


def row(finding, verdict, why="because", test=TEST):
    return {"finding": finding, "verdict": verdict, "why": why, "test": test}


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

    def test_a_wrong_rule_does_not_load(self):
        bad = (row("a", "maybe"), row("a", ASK, test="tests/gear/test_decide.py#test_not_there"),
               row("a", ASK, test="tests/gear/missing.py#test_x"), {"finding": "a", "verdict": ASK})
        for r in bad:
            with self.subTest(row=r), self.assertRaises(RuleError):
                self.decide(r)

    def test_a_finding_named_twice_does_not_load(self):
        with self.assertRaises(RuleError):
            self.decide(row("a", ASK), row("a", REFUSE))

    def test_the_real_rules_load(self):
        Decide.load(CLAUDE_DIR)

    def test_gear_declares_decide_as_its_rule(self):
        self.assertIn({"kind": "rule", "name": "decide", "ref": "harness.gear.decide:Decide"}, gear_block.ITEMS)


if __name__ == "__main__":
    unittest.main()
