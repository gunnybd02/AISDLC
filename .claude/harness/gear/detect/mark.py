"""MarkScan: the text of a commit holds no AI mark (commit.ai_mark: an AI co-author or footer, an AI tool's name or
address, a robot emoji, a Mermaid diagram; utils/git/marks.py) and none of the project's banned words
(commit.banned_word; project.json banned)."""
from __future__ import annotations

from harness.utils.contracts import Detector, Event, Finding
from harness.utils.git.marks import banned_in, marks_in
from harness.utils.shapes import Facts


class MarkScan(Detector):
    """The text of a commit: commit.ai_mark, commit.banned_word."""

    def detect(self, event: Event, facts: Facts) -> list[Finding]:
        """Report commit.ai_mark for each AI mark and commit.banned_word for each banned word in the commit message."""
        if "commit_message" not in facts:
            return []
        text = facts["commit_message"]
        out = [Finding("commit.ai_mark", mark) for mark in marks_in(text)]
        return out + [Finding("commit.banned_word", word) for word in banned_in(text, facts.get("banned", ()))]
