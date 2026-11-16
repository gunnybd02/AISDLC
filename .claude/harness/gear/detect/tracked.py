"""Tracked: plan.none, a write while the session has no approved plan. A write into the harness's own state is
planfiles.py's (write.state), plan or not."""
from __future__ import annotations

from harness.gear.detect.planfiles import in_state
from harness.utils.contracts import Detector, Event, Finding
from harness.utils.shapes import Facts


class Tracked(Detector):
    """A write with no approved plan: plan.none."""

    def detect(self, event: Event, facts: Facts) -> list[Finding]:
        """Report plan.none for each write outside the harness's state while the session has no approved plan."""
        if facts.get("plan") is not None:
            return []
        state = facts.get("state_dir")
        return [Finding("plan.none", path) for path in facts.get("writes", []) if not in_state(path, state)]
