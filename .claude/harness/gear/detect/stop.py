"""StopGuard: stop.unverified, a turn that would end while a code file of the session's plan has no green verify of
its current content (the port's stop_owed, utils/plan/stop.py). A Stop repeated after a block (stop_hook_active), no
plan in force, or no file owed lets the turn end; a failure to look keeps it (fail closed)."""
from __future__ import annotations

from harness.utils.contracts import Detector, Event, Finding
from harness.utils.shapes import Facts


class StopGuard(Detector):
    """A turn that would end with an unverified code file: stop.unverified."""

    def detect(self, event: Event, facts: Facts) -> list[Finding]:
        """Report stop.unverified at a Stop while a code file of the plan has no green verify of its content, or
        when the harness could not look."""
        plan = facts.get("plan")
        if event.kind != "Stop" or event.input.get("stop_hook_active") or not plan:
            return []
        try:
            owed = facts["stop_owed"](plan)
        except Exception as e:
            return [Finding("stop.unverified", f"the harness could not look ({type(e).__name__}: {e})")]
        return [Finding("stop.unverified", ", ".join(owed))] if owed else []
