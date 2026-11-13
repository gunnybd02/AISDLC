"""Tracked: plan.none, a write while the session has no approved plan. A write into the harness's own state is
planfiles.py's (write.state), plan or not."""
from harness.gear.detect.planfiles import in_state
from harness.utils.contracts import Detector, Finding


class Tracked(Detector):
    def detect(self, event, facts):
        if facts.get("plan") is not None:
            return []
        state = facts.get("state_dir")
        return [Finding("plan.none", path) for path in facts.get("writes", []) if not in_state(path, state)]
