"""Decide: the one judge. Each finding is looked up in the rules of gear/rules/*.json; the strongest verdict of all the
findings wins, with the reasons of the findings that gave it. A finding no rule names asks the user, its name and detail
in the question. No finding: allow.
A finding of IN_PLACE_OF_ASK stands in for a person who is not there (child.no_keyboard: a child session, whose keyboard
nobody watches): it counts only when the other findings would ask, and then its row's verdict replaces the question.

A finding row: {"finding": kind, "verdict": allow|ask|refuse, "why": the sentence shown, "test":
"harness/tests/<file>.py#<test>"}; it judges what a detector found (in content, or in a state).
A when row (spec 13 section 7): {"code", "verdict", "why", "when": {fact: value or [values]}, "test"}; it judges the
rule actions translators give (RULE_ACTIONS): it matches an action whose facts equal every key of when (a list means
any of), and a match is a finding of its code, the action's detail in brackets. A when row names only facts of the
vocabulary the translators declare, when one is given. A code or finding is one row across both kinds; a row whose test
is not a test function under harness/tests/ does not load."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional, TypedDict

from harness.utils.contracts import ALLOW, ASK, Finding, ProblemsError, VERDICTS, Verdict

RULES = ("harness", "gear", "rules")  # under the .claude folder
FIELDS = ("finding", "verdict", "why", "test")
WHEN_FIELDS = ("code", "verdict", "why", "when", "test")
VALUE = (str, bool, int)
UNMATCHED = "rule.unmatched"  # no row names it: asked, never allowed
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

    def __init__(self, rules: dict[str, RuleRow], when_rows: Optional[list[dict[str, Any]]] = None) -> None:
        """Keep the rule rows.

        Args:
            rules: {finding kind: its rule row}.
            when_rows: the when rows, in the order of their files; None for none.
        """
        self.rules = rules  # {finding kind: row}
        self.when_rows = list(when_rows or [])
        self.codes = {row["code"]: row for row in self.when_rows}

    @classmethod
    def load(cls, claude_dir: str | Path, rules_dir: Optional[str | Path] = None,
             vocabulary: Optional[set[str]] = None) -> Decide:
        """Load every rules file (*.json) of the rules folder into a judge.

        Args:
            claude_dir: the .claude folder; the rows' tests are looked up under it.
            rules_dir: the folder of the rules files; None for <claude_dir>/harness/gear/rules.
            vocabulary: the facts the translators of the pipeline declare; a when row naming another does not load.
                None leaves the facts unchecked.

        Returns:
            A Decide holding every finding row by kind and every when row.

        Raises:
            RuleError: a file that is not a rules file, a bad row, or two rows for the same finding or code.
        """
        rules, when_rows, problems = {}, [], []
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
                when = isinstance(row, dict) and "when" in row
                why = Decide.when_problem(row, Path(claude_dir), vocabulary) if when else \
                    Decide.row_problem(row, Path(claude_dir))
                key = row.get("code" if when else "finding") if not why else ""
                if why:
                    problems.append(f"{path.name} rule {n}: {why}")
                elif key in rules or any(r["code"] == key for r in when_rows):
                    problems.append(f"{path.name} rule {n}: {key} has a rule already")
                elif when:
                    when_rows.append(row)
                else:
                    rules[key] = row
        if problems:
            raise RuleError(problems)
        return cls(rules, when_rows)

    @staticmethod
    def when_problem(row: dict[str, Any], claude_dir: Path, vocabulary: Optional[set[str]]) -> str:
        """What is wrong with one when row, or "".

        Args:
            row: the row as read.
            claude_dir: the .claude folder the row's test path is read from.
            vocabulary: the facts a when may name; None for any.

        Returns:
            "" for a good row; else why it does not load.
        """
        if sorted(row) != sorted(WHEN_FIELDS) or not all(isinstance(row[k], str) for k in WHEN_FIELDS if k != "when"):
            return f"a when row's fields are exactly {', '.join(WHEN_FIELDS)}; all but when are strings"
        when = row["when"]
        if not isinstance(when, dict) or not when or not all(
                isinstance(v, VALUE) or (isinstance(v, list) and v and all(isinstance(x, VALUE) for x in v))
                for v in when.values()):
            return "when is an object of facts, each a value or a list of values"
        unknown = sorted(set(when) - vocabulary) if vocabulary is not None else []
        if unknown:
            return f"when names {', '.join(unknown)}, which no translator declares"
        return Decide.row_problem({"finding": row["code"], **{k: row[k] for k in ("verdict", "why", "test")}}, claude_dir)

    @staticmethod
    def matches(when: dict[str, Any], facts: dict[str, Any]) -> bool:
        """Whether an action's facts meet a when: every key equal (a list: any of its values).

        Args:
            when: the row's when.
            facts: the rule action's facts.

        Returns:
            True when every key matches.
        """
        return all(k in facts and any(facts[k] == x and type(facts[k]) is type(x)
                                      for x in (v if isinstance(v, list) else [v])) for k, v in when.items())

    def matched(self, actions: list[dict[str, Any]]) -> list[Finding]:
        """The findings of the when rows the rule actions meet: one per row and action, the action's detail kept.

        Args:
            actions: the rule actions of the event (RULE_ACTIONS), each its facts, and an optional detail or details
                by fact.

        Returns:
            Finding(code, detail) for each match, in the order of the actions, then of the rows; for an action marked
            must_match that meets no row, rule.unmatched (which no row names, so it is asked).
        """
        out = []
        for action in (a for a in actions if isinstance(a, dict)):
            hits = [Finding(row["code"], self.detail_of(row["when"], action)) for row in self.when_rows
                    if self.matches(row["when"], action)]
            if not hits and action.get("must_match"):  # an action that must be judged and meets no row is asked
                hits = [Finding(UNMATCHED, f"{action.get('kind', '')}: {action.get('detail', '')}")]
            out += hits
        return out

    @staticmethod
    def detail_of(when: dict[str, Any], action: dict[str, Any]) -> str:
        """The words a match shows in brackets: the detail of the first fact of the when that has one (details), else
        the action's detail.

        Args:
            when: the matched row's when.
            action: the rule action.

        Returns:
            The detail, "" when there is none.
        """
        details = action.get("details") if isinstance(action.get("details"), dict) else {}
        return str(next((details[k] for k in when if k in details), action.get("detail", "")))

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
        row = self.rules.get(finding.kind) or self.codes.get(finding.kind)
        if row is None:
            return ASK, f"no rule for the finding {finding.kind}{detail}: allow it?"
        return row["verdict"], row["why"] + detail
