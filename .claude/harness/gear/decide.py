"""Decide: the one judge. Each finding is looked up in the rules of gear/rules/*.json; the strongest verdict of all the
findings wins, with the reasons of the findings that gave it. A finding no rule names asks the user, its name and detail
in the question. No finding: allow.

A rule row: {"finding": kind, "verdict": allow|ask|refuse, "why": the sentence shown, "test": "tests/<file>.py#<test>"};
a row whose test is not a test function under tests/ does not load."""
import json
import re
from pathlib import Path

from harness.utils.contracts import ALLOW, ASK, VERDICTS, Verdict

RULES = ("harness", "gear", "rules")  # under the .claude folder
FIELDS = ("finding", "verdict", "why", "test")
TEST = re.compile(r"^tests/(?:[A-Za-z_][\w]*/)*test_\w+\.py#test_\w+$")


class RuleError(Exception):
    def __init__(self, problems):
        super().__init__("\n".join(problems))
        self.problems = problems


class Decide:
    def __init__(self, rules):
        self.rules = rules  # {finding kind: row}

    @classmethod
    def load(cls, claude_dir, rules_dir=None):
        rules, problems = {}, []
        for path in sorted(Path(rules_dir or Path(claude_dir).joinpath(*RULES)).glob("*.json")):
            try:
                rows = json.loads(path.read_text(encoding="utf-8-sig"))["rules"]
            except (ValueError, KeyError, TypeError) as e:
                problems.append(f"{path.name}: not a rules file ({e})")
                continue
            if not isinstance(rows, list):
                problems.append(f"{path.name}: rules is a list of rows")
                continue
            for n, row in enumerate(rows, 1):
                why = Decide.row_problem(row, Path(claude_dir))
                if why:
                    problems.append(f"{path.name} rule {n}: {why}")
                elif row["finding"] in rules:
                    problems.append(f"{path.name} rule {n}: the finding {row['finding']} has a rule already")
                else:
                    rules[row["finding"]] = row
        if problems:
            raise RuleError(problems)
        return cls(rules)

    @staticmethod
    def row_problem(row, claude_dir):
        if not isinstance(row, dict) or sorted(row) != sorted(FIELDS) or not all(isinstance(v, str) for v in row.values()):
            return f"fields are exactly {', '.join(FIELDS)}, each a string"
        if row["verdict"] not in VERDICTS:
            return f"verdict '{row['verdict']}' is not one of {', '.join(VERDICTS)}"
        file, _, name = row["test"].partition("#")
        path = claude_dir / file
        try:
            found = TEST.match(row["test"]) and path.is_file() and \
                re.search(rf"^\s*def {name}\(", path.read_text(encoding="utf-8-sig"), re.M)
        except UnicodeDecodeError:
            found = False
        return "" if found else f"the test {row['test']} is not a test function of a file under tests/"

    def decide(self, findings):
        if not findings:
            return Verdict(ALLOW)
        judged = [self.judge(f) for f in findings]
        decision = max((v for v, _ in judged), key=VERDICTS.index)
        reason = "; ".join(dict.fromkeys(why for v, why in judged if v == decision))
        return Verdict(decision, reason, tuple(findings))

    def judge(self, finding):
        detail = f" ({finding.detail})" if finding.detail else ""
        row = self.rules.get(finding.kind)
        if row is None:
            return ASK, f"no rule for the finding {finding.kind}{detail}: allow it?"
        return row["verdict"], row["why"] + detail
