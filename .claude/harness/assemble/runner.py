"""Runner: one event through translate (facts) -> detect (findings) -> decide (the verdict). Each fact has one
translator: two that give the same fact are an error of the recipe, never a silent overwrite."""


class RunnerError(ValueError):
    pass


class Runner:
    def __init__(self, translators, detectors, decide):
        self.translators, self.detectors, self.decide = list(translators), list(detectors), decide

    def run(self, event):
        facts = {}
        for translator in self.translators:
            new = translator.translate(event)
            twice = sorted(set(new) & set(facts))
            if twice:
                raise RunnerError(f"{type(translator).__name__} gives facts another translator gave: {', '.join(twice)}")
            facts.update(new)
        findings = [f for detector in self.detectors for f in detector.detect(event, facts)]
        return self.decide.decide(findings)
