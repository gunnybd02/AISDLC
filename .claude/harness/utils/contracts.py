"""What the blocks share: the event of a hook, a finding, a verdict, and the base classes of a translator, a detector
and a port. The verdict words live here and in gear/decide/arbiter.py only (verdict_net)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from harness.utils.shapes import Facts

ALLOW, ASK, REFUSE = "allow", "ask", "refuse"
VERDICTS = (ALLOW, ASK, REFUSE)  # from the weakest to the strongest
CLAUDE_DECISION = {ASK: "ask", REFUSE: "deny"}  # what Claude Code reads; allow says nothing
PERMISSIONS_KEY = "allow"  # the list of allowed tools in Claude Code's settings.json (permissions), not a verdict
YES = "Duy\u1ec7t"  # the user's word in a form that approves (a plan, a grant)


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
    def translate(self, event: Event) -> Facts:
        """Describe one hook call as facts.

        Args:
            event: the hook call of Claude Code.

        Returns:
            The facts this translator gives, by fact name ({} when the call is none of its business).
        """
        ...


class Detector(ABC):
    """Reports findings about an event and its facts; it never judges."""

    @abstractmethod
    def detect(self, event: Event, facts: Facts) -> list[Finding]:
        """Report what this detector sees in one hook call.

        Args:
            event: the hook call of Claude Code.
            facts: what the translators and ports said about the call, by fact name.

        Returns:
            The findings, [] when there is nothing to report.
        """
        ...


class Port(ABC):
    """Reads facts from outside the harness (the ledger, git) for the detectors. A fact that costs a read (git) is
    given as a view the detector calls only when the call needs it."""

    @abstractmethod
    def read(self, event: Event) -> Facts:
        """Read the facts this port gives for one hook call.

        Args:
            event: the hook call of Claude Code.

        Returns:
            The facts by fact name; a fact that costs a read may be a callable view.
        """
        ...


READ, WRITE = "read", "write"
EFFECTS = (READ, WRITE)


class ActionError(Exception):
    """What an action answers when it will not do what it was asked; the model reads the message."""


@dataclass(frozen=True)
class ActionContext:
    """What an action is given: only the ports it names in needs."""
    ports: dict


class McpAction(ABC):
    """One action `run` reaches, a class listed in the ACTIONS literal of its file in mcp/actions/ as ("block.name",
    "Class"). block and name match that entry; args_schema is a JSON schema of an object; needs names its ports; effect
    is read or write, and a write is judged by the rules before it runs."""
    block = ""
    name = ""
    summary = ""
    args_schema = {"type": "object", "properties": {}, "required": []}
    needs = ()
    effect = READ

    @abstractmethod
    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Do the action.

        Args:
            ctx: the ports the action names in needs.
            args: the arguments of the call, already checked against args_schema.

        Returns:
            The text for the model.

        Raises:
            ActionError: the action will not do what it was asked; the model reads the message.
        """
        ...


def judged_allow(verdict: Verdict) -> bool:
    """Whether a verdict lets a write action run: an allow that a rule row decided. An allow with no finding is no rule's
    decision (write-unjudged), and an ask is not an allow: the server cannot ask the user.

    Args:
        verdict: the verdict of the rules on the action's event.

    Returns:
        True only for an allow with at least one finding.
    """
    return verdict.decision == ALLOW and bool(verdict.findings)


def asked(verdict: Verdict) -> bool:
    """Whether the rules want the user's word before the call runs.

    Args:
        verdict: the verdict of the rules on a call.

    Returns:
        True when the decision is ask.
    """
    return verdict.decision == ASK


def refused(verdict: Verdict) -> bool:
    """Whether the rules stop the call.

    Args:
        verdict: the verdict of the rules on a call.

    Returns:
        True when the decision is refuse.
    """
    return verdict.decision == REFUSE


PREPARE, EXECUTE, DELIVER = "prepare", "execute", "deliver"
PHASES = (EXECUTE, DELIVER)  # the phases in which a ticket's plan is in force
