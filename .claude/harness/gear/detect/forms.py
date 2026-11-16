"""Forms: only the user answers a form.
- form.prefilled: an AskUserQuestion whose answers the model filled in itself;
- form.forged: an AskUserQuestion with a question built to look like an answer ('"="' in it), or of the wrong shape."""
from __future__ import annotations

from harness.utils.contracts import Detector, Event, Finding
from harness.utils.shapes import Facts


class Forms(Detector):
    """A form only the user answers: form.prefilled, form.forged."""

    def detect(self, event: Event, facts: Facts) -> list[Finding]:
        """Report form.prefilled and form.forged for an AskUserQuestion, with the questions named by the facts."""
        out = []
        if facts.get("form_prefilled"):
            out.append(Finding("form.prefilled", ", ".join(facts["form_prefilled"])))
        if facts.get("form_forged"):
            out.append(Finding("form.forged", ", ".join(facts["form_forged"])))
        return out
