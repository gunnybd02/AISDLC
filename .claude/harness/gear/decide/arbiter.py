"""Decide: the one judge. Each finding is looked up in the rules of gear/rules/*.json; the strongest verdict of all the
findings wins, with the reasons of the findings that gave it. A finding no rule names asks the user, its name and detail
in the question. No finding: allow.
A finding of IN_PLACE_OF_ASK stands in for a person who is not there (child.no_keyboard: a child session, whose keyboard
nobody watches): it counts only when the other findings would ask, and then its row's verdict replaces the question.

A rule row: {"finding": kind, "verdict": allow|ask|refuse, "why": the sentence shown, "test": "harness/tests/<file>.py#<test>"};
a row whose test is not a test function under harness/tests/ does not load."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional, TypedDict

from harness.utils.contracts import ALLOW, ASK, Finding, ProblemsError, VERDICTS, Verdict

RULES = ("harness", "gear", "rules")  # under the .claude folder
FIELDS = ("finding", "verdict", "why", "test")
IN_PLACE_OF_ASK = ("child.no_keyboard",)
TEST = re.compile(r"^harness/tests/(?:[A-Za-z_][\w]*/)*test_\w+\.py#test_\w+$")


class RuleRow(TypedDict):
    """One row of a rules file: the finding kind it judges, its verdict (allow, ask or refuse), the sentence shown,
    and the test that proves it ("harness/tests/<file>.py#<test>")."""
    finding: str
    verdict: str
    why: str
    test: str


class RuleError(ProblemsError):
    """The rules files do not load; problems holds one line per bad file or row."""


class Decide:
    """The judge: turns the findings of a hook call into one verdict by the rule rows."""

    def __init__(self, rules: dict[str, RuleRow]) -> None:
        """Keep the rule rows.

        Args:
            rules: {finding kind: its rule row}.
        """
        self.rules = rules  # {finding kind: row}

    @classmethod
    def load(cls, claude_dir: str | Path, rules_dir: Optional[str | Path] = None) -> Decide:
        """Load every rules file (*.json) of the rules folder into a judge.

        Args:
            claude_dir: the .claude folder; the rows' tests are looked up under it.
            rules_dir: the folder of the rules files; None for <claude_dir>/harness/gear/rules.

        Returns:
            A Decide holding every row, by finding kind.

        Raises:
            RuleError: a file that is not a rules file, a bad row, or two rows for the same finding.
        """
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
    def row_problem(row: Any, claude_dir: Path) -> str:
        """What is wrong with one row of a rules file, or "".

        Args:
            row: the row as read from the JSON file (any JSON value; a good one is a RuleRow).
            claude_dir: the .claude folder the row's test path is read from.

        Returns:
            "" for a good row; else why it does not load: wrong fields, an unknown verdict, or a test that is not a
            test function of a file under harness/tests/.
        """
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
        return "" if found else f"the test {row['test']} is not a test function of a file under harness/tests/"

    def decide(self, findings: list[Finding]) -> Verdict:
        """The verdict on the findings of one hook call.

        Args:
            findings: what the detectors reported.

        Returns:
            allow with no reason when there is no finding; else the strongest verdict of the findings, the reasons of
            the findings that gave it (joined by "; ", each once) and every finding. A stand-in finding (IN_PLACE_OF_ASK)
            is left out, unless the verdict would be ask: then its row's verdict and reason come first.
        """
        stand_in = [f for f in findings if f.kind in IN_PLACE_OF_ASK]
        findings = [f for f in findings if f.kind not in IN_PLACE_OF_ASK]
        if not findings:
            return Verdict(ALLOW)
        judged = [self.judge(f) for f in findings]
        decision = max((v for v, _ in judged), key=VERDICTS.index)
        reason = "; ".join(dict.fromkeys(why for v, why in judged if v == decision))
        if decision == ASK and stand_in:  # nobody would answer the question: the stand-in's row decides
            first, why = self.judge(stand_in[0])
            return Verdict(first, f"{why} Why it would have asked: {reason}", tuple(findings + stand_in[:1]))
        return Verdict(decision, reason, tuple(findings))

    def judge(self, finding: Finding) -> tuple[str, str]:
        """The verdict word and the reason for one finding.

        Args:
            finding: one finding of a detector.

        Returns:
            (verdict word, why): its rule row's verdict and sentence with the finding's detail in brackets; ask with a
            question naming the finding when no row names it.
        """
        detail = f" ({finding.detail})" if finding.detail else ""
        row = self.rules.get(finding.kind)
        if row is None:
            return ASK, f"no rule for the finding {finding.kind}{detail}: allow it?"
        return row["verdict"], row["why"] + detail
