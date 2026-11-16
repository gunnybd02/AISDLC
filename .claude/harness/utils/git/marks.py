"""The marks commit and merge request text never holds: AI attribution (a co-author or a footer naming an AI tool, a
robot emoji, an AI vendor's noreply address) and Mermaid diagrams. Banned words are the project's own (project.json
banned)."""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Optional

AI_MARKS = (
    ("an AI co-author", re.compile(r"co-authored-by:.*\b(claude|anthropic|openai|chatgpt|copilot|gemini|cursor)\b",
                                   re.I)),
    ("an AI footer", re.compile(r"\b(generated|written|created) (with|by|using) (claude|chatgpt|copilot|gemini|cursor|"
                                r"an? ai\b|ai\b)", re.I)),
    ("an AI tool's name", re.compile(r"\bclaude[ -]code\b|claude\.(ai|com)", re.I)),
    ("an AI vendor's address", re.compile(r"noreply@(anthropic|openai)\.com", re.I)),
    ("a robot emoji", re.compile("\U0001F916")),
    ("a Mermaid diagram", re.compile(r"```\s*mermaid", re.I)),
)


def marks_in(text: Optional[str]) -> list[str]:
    """The AI marks a text holds.

    Args:
        text: a commit message or a merge request's text; None is no text.

    Returns:
        The name of each mark of AI_MARKS found ("an AI co-author", "a robot emoji"...), in AI_MARKS' order.
    """
    return [name for name, pattern in AI_MARKS if pattern.search(str(text or ""))]


def banned_in(text: Optional[str], words: Iterable[str]) -> list[str]:
    """The banned words a text holds, as whole words, case ignored.

    Args:
        text: a commit message or a merge request's text; None is no text.
        words: the project's banned words (project.json banned).

    Returns:
        Each word found, as given, in the order of words.
    """
    low = str(text or "").lower()
    return [w for w in words if re.search(rf"(?<!\w){re.escape(w.lower())}(?!\w)", low)]
