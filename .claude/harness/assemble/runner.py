"""Runner: one event through facts (ports, then translators) -> detect (findings) -> decide (the verdict) -> act (what
the harness writes back, such as an approval, and the notes it gives the model). Each fact has one giver: two that
give the same fact are an error of the recipe, never a silent overwrite."""
from dataclasses import dataclass

from harness.utils.contracts import Port


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
