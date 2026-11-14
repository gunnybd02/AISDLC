"""RawCommit: commit.raw, a shell line that commits (gear/translate/git.py), safe to read or not. Commits go through
run('plan', 'step_done') or run('git', 'commit'), where the harness checks the plan's change and commits it itself (utils/plan/steps.py)."""
from harness.utils.contracts import Detector, Finding


class RawCommit(Detector):
    def detect(self, event, facts):
        target = facts.get("git_commit")
        if event.kind != "PreToolUse" or not target:
            return []
        return [Finding("commit.raw", target.get("unsafe") or f"git commit in {target['repo']}")]
