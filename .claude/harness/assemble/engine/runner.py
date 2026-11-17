"""Runner: one event through facts (ports, then translators) -> detect (findings) -> decide (the verdict) -> act (what
the harness writes back, such as an approval, and the notes it gives the model). Each fact has one giver: two that
give the same fact are an error of the pipeline, never a silent overwrite."""
from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Protocol

from harness.utils.contracts import Detector, Event, Finding, Port, Translator, Verdict
from harness.utils.git.asks import accepts
from harness.utils.ledger import store
from harness.utils.plan import stop
from harness.utils.plan.files import allows, relative
from harness.utils.plan.approval import approvals
from harness.utils.plan.closing import close_answers, delivery
from harness.utils.plan.life import accepts as drop_accepts
from harness.utils.plan.ship import mr_accepts
from harness.utils.gateway.release import accepts as release_accepts
from harness.utils.orchestra import child, synced
from harness.utils.orchestra.cleanup import removal_accepts
from harness.utils.plan.request import FORM_ONLY
from harness.utils.shapes import Facts

BOUND = ("GATE: this session is the child {name} of the delegated plan {plan}: call run('orchestra', 'take') first; "
         "never AskUserQuestion, never a plan of your own.")

if TYPE_CHECKING:
    from harness.assemble.engine.ports import LedgerPort


class RunnerError(ValueError):
    """Two givers of the pipeline give the same fact."""


class Decider(Protocol):
    """The decide of gear (gear/decide/arbiter.py Decide), loaded by name: assemble names it without importing gear."""

    def decide(self, findings: list[Finding]) -> Verdict:
        """The verdict on the findings of one event."""
        ...


@dataclass(frozen=True)
class Outcome:
    verdict: object
    notes: tuple = ()


class Runner:
    """One event through the ports and translators (facts), the detectors (findings), decide (the verdict) and act."""

    def __init__(self, translators: Sequence[Translator], detectors: Sequence[Detector], decide: Decider,
                 ports: Sequence[Port] = (), act: Optional[Act] = None) -> None:
        """Keep the pipeline's parts; the ports give their facts before the translators.

        Args:
            translators: the translators of the pipeline, in order.
            detectors: the detectors of the pipeline, in order.
            decide: the decide of gear, which turns findings into the verdict.
            ports: the ports that read facts from outside (PlanState).
            act: what writes back after the verdict, or None to write nothing.
        """
        self.givers = list(ports) + list(translators)
        self.detectors, self.decide, self.act = list(detectors), decide, act

    def run(self, event: Event) -> Outcome:
        """Run one event through the pipeline.

        Args:
            event: the hook call (or the event an MCP action is judged as).

        Returns:
            The Outcome: the verdict and the notes for the model.

        Raises:
            RunnerError: two givers give the same fact.
        """
        facts, findings = {}, []
        for giver in self.givers:
            try:
                new = giver.read(event) if isinstance(giver, Port) else giver.translate(event)
                if not isinstance(new, dict):
                    raise TypeError(f"gave {type(new).__name__}, not a dict of facts")
            except Exception as e:  # a gear fault is a finding, never a crash (spec 13 section 7)
                findings.append(fault(event, giver, e))
                continue
            twice = sorted(set(new) & set(facts))
            if twice:
                raise RunnerError(f"{type(giver).__name__} gives facts another giver gave: {', '.join(twice)}")
            facts.update(new)
        for detector in self.detectors:
            try:
                findings += detector.detect(event, facts)
            except Exception as e:
                findings.append(fault(event, detector, e))
        verdict = self.decide.decide(findings)
        notes = self.act.run(event, facts, verdict) if self.act else []
        return Outcome(verdict, tuple(notes))


FAULT, FAULT_AFTER = "gear.fault", "gear.fault_after"


def fault(event: Event, gear: object, error: Exception) -> Finding:
    """The finding of a gear that raised: gear.fault before a tool call (a refusal: fail closed), gear.fault_after on any
    other event (an allow: a broken gear never holds a turn or a prompt). The fault is also said on stderr.

    Args:
        event: the hook call.
        gear: the giver or detector that raised.
        error: what it raised.

    Returns:
        The Finding, its detail the gear's class and the error.
    """
    detail = f"{type(gear).__name__}: {type(error).__name__}: {error}"[:300]
    sys.stderr.write(f"harness: a gear failed on {event.kind}: {detail}\n")
    return Finding(FAULT if event.kind == "PreToolUse" else FAULT_AFTER, detail)


HARNESS_TOOLS = "mcp__harness__"  # the tools of the harness's own MCP server, as Claude Code names them


class Act:
    """What the harness writes back after the verdict, and the notes it gives the model: an approval of a plan
    (utils/plan/approval.py), a delivery (utils/plan/closing.py), and each finding kept as a rule decision with the word
    Claude Code was given."""

    def __init__(self, port: LedgerPort) -> None:
        """Keep the ledger port it writes to.

        Args:
            port: the ledger port.
        """
        self.port = port

    def run(self, event: Event, facts: Facts, verdict: Verdict) -> list[str]:
        """Write back what the event and its verdict call for, and give the notes for the model.

        Args:
            event: the hook call.
            facts: the facts of the call (plan, answers, writes, git_commit, harness_cli...).
            verdict: the verdict decide gave.

        Returns:
            The notes for the model: approvals, accepted asks, closes, deliveries, a form-only reminder...
        """
        notes = []
        if event.kind == "UserPromptSubmit" or (event.kind == "PreToolUse" and (
                event.tool.startswith(HARNESS_TOOLS) or facts.get("harness_cli"))):
            self.port.touch_session(event.session)
        if event.kind == "UserPromptSubmit" and event.session:
            text = str(event.input.get("prompt") or "")
            waiting = self.port.prompt(event.session, text)
            if waiting:
                notes.append(FORM_ONLY.format(plan=waiting["plan_id"], rev=waiting["rev"],
                                              question=waiting.get("question", "")))
            if text.lstrip().startswith(child.START):  # a brief as the first prompt makes the session a child
                role = self.port.write(lambda con, rec: child.bind(con, event.session, text))
                if role:
                    notes.append(BOUND.format(name=role["name"], plan=role["plan"]))
        if event.kind == "PostToolUse":
            notes += approvals(self.port, event.session, facts.get("answers") or {})
            notes += accepts(self.port, facts.get("answers") or {})
            notes += close_answers(self.port, event.session, facts.get("answers") or {})
            notes += drop_accepts(self.port, facts.get("answers") or {})
            notes += mr_accepts(self.port, facts.get("answers") or {})
            notes += release_accepts(self.port, facts.get("answers") or {})
            notes += removal_accepts(self.port, facts.get("answers") or {})  # a remove checklist the user ticked
            notes += synced.waiver_accepts(self.port, facts.get("answers") or {})  # a child closed without its copy
            notes += synced.seen(self.port, event)  # a Drive answer shows copies of this session's orchestra run
            notes += delivery(self.port, event.session, facts.get("git_commit"), facts.get("plan"))
            notes += store.uploaded(self.port, event)  # a Drive tool answered with a copy of the ledger
            plan = facts.get("plan")
            if plan and any(relative(path, plan["root"]) is not None and allows(plan, relative(path, plan["root"]))
                            for path in facts.get("writes", [])):
                self.port.back(event.session)  # a write to a plan file in deliver goes back to execute
        if event.kind == "Stop" and any(f.kind == "store.unsaved" for f in verdict.findings):
            store.asked(self.port, event.session)  # a turn is held once for the same unsaved work
        if event.kind == "Stop" and facts.get("plan") and "stop_foreign" in facts:
            notes += stop.foreign_note(facts["stop_foreign"], facts["plan"])  # a change another writer made
        self.port.record(event, facts, verdict)  # the call itself: its rows, its findings, what it wrote and ran
        return notes
