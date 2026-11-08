"""Runner: one event through translate (facts) -> detect (findings) -> decide (the verdict)."""


class Runner:
    def __init__(self, translators, detectors, decide):
        self.translators, self.detectors, self.decide = list(translators), list(detectors), decide

    def run(self, event):
        facts = {}
        for translator in self.translators:
            facts.update(translator.translate(event))
        findings = [f for detector in self.detectors for f in detector.detect(event, facts)]
        return self.decide.decide(findings)
