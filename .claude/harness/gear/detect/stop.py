"""StopGuard: stop.unverified, a turn that would end while a code file of the session's plan has no green verify of
its current content (the port's stop_owed, utils/plan/stop.py). A Stop repeated after a block (stop_hook_active), no
plan in force, or no file owed lets the turn end; a failure to look keeps it (fail closed)."""
from harness.utils.contracts import Detector, Finding


class StopGuard(Detector):
    def detect(self, event, facts):
        plan = facts.get("plan")
        if event.kind != "Stop" or event.input.get("stop_hook_active") or not plan:
            return []
        try:
            owed = facts["stop_owed"](plan)
        except Exception as e:
            return [Finding("stop.unverified", f"the harness could not look ({type(e).__name__}: {e})")]
        return [Finding("stop.unverified", ", ".join(owed))] if owed else []
