"""StoreGuard: store.unsaved, a turn that would end while work of the ledger is in no copy of the store (the port's
store_owed, utils/ledger/store.py: commits, plan events, pushes since the newest copy the store holds). It holds a turn
once for the same work, and only when a store folder is set. A Stop repeated after a block lets the turn end, and so
does a failure to look: the store never keeps a session from going on."""
from __future__ import annotations

from harness.utils.contracts import Detector, Event, Finding
from harness.utils.shapes import Facts


class StoreGuard(Detector):
    """A turn that would end with work in no copy of the store: store.unsaved."""

    def detect(self, event: Event, facts: Facts) -> list[Finding]:
        """Report store.unsaved at a Stop while work of the ledger is in no copy of the store; nothing when it
        could not look."""
        if event.kind != "Stop" or event.input.get("stop_hook_active") or "store_owed" not in facts:
            return []
        try:
            owed = facts["store_owed"]()
        except Exception:
            return []
        return [Finding("store.unsaved", ", ".join(owed))] if owed else []
