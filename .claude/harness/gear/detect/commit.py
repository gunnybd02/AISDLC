"""RawCommit: commit.raw, a shell line that commits (gear/translate/git.py), safe to read or not. Commits go through
run('plan', 'step_done') or run('git', 'commit'), where the harness checks the plan's change and commits it itself (utils/plan/steps.py)."""
from __future__ import annotations

from harness.utils.contracts import Detector, Event, Finding
from harness.utils.shapes import Facts


class RawCommit(Detector):
    """A shell line that commits: commit.raw."""

    def detect(self, event: Event, facts: Facts) -> list[Finding]:
        """Report commit.raw for a shell line that commits, before it runs: why it is unsafe, or the repository."""
        target = facts.get("git_commit")
        if event.kind != "PreToolUse" or not target:
            return []
        return [Finding("commit.raw", target.get("unsafe") or f"git commit in {target['repo']}")]
