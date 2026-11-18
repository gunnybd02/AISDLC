"""StopGuard: stop.unverified, a turn that would end while a code file of the session's plan has no green verify of
its current content (the port's stop_owed, utils/plan/stop.py); stop.outside, a turn that would end while a file the
session changed is outside the plan and still holds that change (the port's stop_outside). A Stop repeated after a
block (stop_hook_active), no plan in force, or nothing owed lets the turn end; a failure to look keeps it (fail
closed)."""
from __future__ import annotations

from harness.utils.contracts import Detector, Event, Finding
from harness.utils.shapes import Facts


class StopGuard(Detector):
    """A turn that would end with an unverified code file (stop.unverified) or a change outside the plan
    (stop.outside)."""

    def detect(self, event: Event, facts: Facts) -> list[Finding]:
        """Report stop.unverified at a Stop while a code file of the plan has no green verify of its content, and
        stop.outside while a file the session changed is outside the plan; each also when the harness could not
        look."""
        plan = facts.get("plan")
        if event.kind != "Stop" or event.input.get("stop_hook_active") or not plan:
            return []
        out = []
        for kind, name in (("stop.unverified", "stop_owed"), ("stop.outside", "stop_outside")):
            if name == "stop_outside" and name not in facts:
                continue  # a port that cannot tell the session's changes has nothing to hold the turn for
            try:
                files = facts[name](plan)
            except Exception as e:
                out.append(Finding(kind, f"the harness could not look ({type(e).__name__}: {e})"))
                continue
            if files:
                out.append(Finding(kind, ", ".join(files)))
        return out
