"""CommitFacts: what a commit the harness is about to make holds (the event HarnessCommit, built by step_done's
judge): commit_message, commit_repo, commit_files (from the repository root) and commit_added, the lines each adds."""
from __future__ import annotations

from harness.utils.contracts import Event, Translator
from harness.utils.git.staged_diff import added_lines
from harness.utils.shapes import Facts

TOOL = "HarnessCommit"


class CommitFacts(Translator):
    """What a commit the harness is about to make holds (the event HarnessCommit)."""

    def translate(self, event: Event) -> Facts:
        """Give commit_message, commit_repo, commit_files and commit_added ({file: [added lines]}) for a
        HarnessCommit before it runs; else {}."""
        if event.tool != TOOL or event.kind != "PreToolUse":
            return {}
        repo, files = event.input.get("repo"), list(event.input.get("files") or [])
        return {"commit_message": str(event.input.get("message") or ""), "commit_repo": repo, "commit_files": files,
                "commit_added": added_lines(repo, files) if repo else {}}
