"""What the blocks share: the event of a hook, a finding, a verdict, and the base classes of a translator, a detector
and a port. The verdict words live here and in gear/decide.py only (verdict_net)."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

ALLOW, ASK, REFUSE = "allow", "ask", "refuse"
VERDICTS = (ALLOW, ASK, REFUSE)  # from the weakest to the strongest
CLAUDE_DECISION = {ASK: "ask", REFUSE: "deny"}  # what Claude Code reads; allow says nothing


@dataclass(frozen=True)
class Event:
    """One hook call of Claude Code; response is the tool's answer, given to PostToolUse only."""
    kind: str
    tool: str = ""
    input: dict = field(default_factory=dict)
    session: str = ""
    cwd: str = ""
    response: object = None


@dataclass(frozen=True)
class Finding:
    """Something a detector saw; only decide turns it into a verdict."""
    kind: str
    detail: str = ""


@dataclass(frozen=True)
class Verdict:
    decision: str
    reason: str = ""
    findings: tuple = ()


class Translator(ABC):
    """Describes what a tool call does, as facts; it never judges."""

    @abstractmethod
    def translate(self, event: Event) -> dict:
        ...


class Detector(ABC):
    """Reports findings about an event and its facts; it never judges."""

    @abstractmethod
    def detect(self, event: Event, facts: dict) -> list:
        ...


class Port(ABC):
    """Reads facts from outside the harness (git, files) for a translator or a detector."""

    @abstractmethod
    def read(self, event: Event) -> dict:
        ...
