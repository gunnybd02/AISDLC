"""Runner: one event through facts (ports, then translators) -> detect (findings) -> decide (the verdict) -> act (what
the harness writes back, such as an approval, and the notes it gives the model). Each fact has one giver: two that
give the same fact are an error of the recipe, never a silent overwrite."""
from dataclasses import dataclass

from harness.utils.contracts import CLAUDE_DECISION, Port
from harness.utils.plan.approval import approvals
from harness.utils.plan.closing import delivery


class RunnerError(ValueError):
    pass


@dataclass(frozen=True)
class Outcome:
    verdict: object
    notes: tuple = ()


class Runner:
    def __init__(self, translators, detectors, decide, ports=(), act=None):
        self.givers = list(ports) + list(translators)
        self.detectors, self.decide, self.act = list(detectors), decide, act

    def run(self, event):
        facts = {}
        for giver in self.givers:
            new = giver.read(event) if isinstance(giver, Port) else giver.translate(event)
            twice = sorted(set(new) & set(facts))
            if twice:
                raise RunnerError(f"{type(giver).__name__} gives facts another giver gave: {', '.join(twice)}")
            facts.update(new)
        findings = [f for detector in self.detectors for f in detector.detect(event, facts)]
        verdict = self.decide.decide(findings)
        notes = self.act.run(event, facts, verdict) if self.act else []
        return Outcome(verdict, tuple(notes))


class Act:
    """What the harness writes back after the verdict, and the notes it gives the model: an approval of a plan
    (utils/plan/approval.py), a delivery (utils/plan/closing.py), and each finding kept as a rule decision with the word
    Claude Code was given."""

    def __init__(self, port):
        self.port = port

    def run(self, event, facts, verdict):
        notes = []
        if event.kind == "PostToolUse":
            notes += approvals(self.port, event.session, facts.get("answers") or {})
            notes += delivery(self.port, event.session, facts.get("git_commit"), facts.get("plan"))
        for finding in verdict.findings:
            self.port.decision(event, facts.get("plan"), finding, CLAUDE_DECISION.get(verdict.decision, verdict.decision))
        return notes
