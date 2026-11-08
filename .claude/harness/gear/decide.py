"""Decide: the one judge. Each finding is looked up in the rules of gear/rules/*.json; the strongest verdict of all the
findings wins, with the reasons of the findings that gave it. A finding no rule names asks the user, its name and detail
in the question. No finding: allow.

A rule row: {"finding": kind, "verdict": allow|ask|refuse, "why": the sentence shown, "test": "tests/<file>.py#<test>"};
a row whose test does not exist does not load."""
import json
import re
from pathlib import Path

from harness.utils.contracts import ALLOW, ASK, VERDICTS, Verdict

RULES_DIR = Path(__file__).with_name("rules")
FIELDS = ("finding", "verdict", "why", "test")


class RuleError(Exception):
    def __init__(self, problems):
        super().__init__("\n".join(problems))
        self.problems = problems


class Decide:
    def __init__(self, rules):
        self.rules = rules  # {finding kind: row}

    @classmethod
    def load(cls, claude_dir, rules_dir=RULES_DIR):
        rules, problems = {}, []
        for path in sorted(Path(rules_dir).glob("*.json")):
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))["rules"]
            except (ValueError, KeyError, TypeError) as e:
                problems.append(f"{path.name}: not a rules file ({e})")
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
        if not name or not path.is_file() or not re.search(rf"^\s*def {re.escape(name)}\(", path.read_text(encoding="utf-8"), re.M):
            return f"the test {row['test']} does not exist"
        return ""

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
