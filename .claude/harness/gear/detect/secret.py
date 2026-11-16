"""SecretScan: commit.secret, a line a commit adds that holds a secret: a private key, a cloud or forge token, an API
key (the shapes of utils/ledger/mask.py). Only the added lines are read (gear/translate/commit.py)."""
from __future__ import annotations

from harness.utils.contracts import Detector, Event, Finding
from harness.utils.ledger.mask import SECRETS
from harness.utils.shapes import Facts

class SecretScan(Detector):
    """A secret in a line a commit adds: commit.secret."""

    def detect(self, event: Event, facts: Facts) -> list[Finding]:
        """Report commit.secret for each kind of secret in the lines a commit adds, one finding per file and kind."""
        out = []
        for path, lines in sorted((facts.get("commit_added") or {}).items()):
            kinds = sorted({kind for line in lines for kind, pattern in SECRETS.items() if pattern.search(line)})
            out += [Finding("commit.secret", f"{path} holds {kind}") for kind in kinds]
        return out
