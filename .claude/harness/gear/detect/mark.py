"""MarkScan: the text of a commit holds no AI mark (commit.ai_mark: an AI co-author or footer, an AI tool's name or
address, a robot emoji, a Mermaid diagram; utils/git/marks.py) and none of the project's banned words
(commit.banned_word; project.json banned)."""
from harness.utils.contracts import Detector, Finding
from harness.utils.git.marks import banned_in, marks_in


class MarkScan(Detector):
    def detect(self, event, facts):
        if "commit_message" not in facts:
            return []
        text = facts["commit_message"]
        out = [Finding("commit.ai_mark", mark) for mark in marks_in(text)]
        return out + [Finding("commit.banned_word", word) for word in banned_in(text, facts.get("banned", ()))]
