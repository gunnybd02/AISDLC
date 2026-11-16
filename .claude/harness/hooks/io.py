"""HookIO: the hook JSON of Claude Code becomes an Event, and a verdict becomes what Claude Code reads. Allow says
nothing, so Claude Code's own permissions still apply. Only PreToolUse takes a decision; the notes of the act step
(an approval, a delivery) reach the model as additionalContext when there is no decision to give."""
from __future__ import annotations

import json
from collections.abc import Sequence

from harness.utils.contracts import CLAUDE_DECISION, Event, Verdict, refused

DECIDES = "PreToolUse"


class HookError(ValueError):
    """The hook payload is not one Claude Code sends: not JSON, no hook_event_name, or a tool_input not an object."""


class HookIO:
    """The hook JSON of Claude Code in (an Event) and out (what Claude Code reads)."""

    @staticmethod
    def read(text: str) -> Event:
        """Read the hook JSON Claude Code gives on stdin as an Event.

        Args:
            text: the hook payload (JSON) with hook_event_name, tool_name, tool_input, session_id, cwd and
                tool_response.

        Returns:
            The Event: its input is tool_input, {"prompt"} for UserPromptSubmit, {"stop_hook_active"} for Stop.

        Raises:
            HookError: the payload is not JSON, has no hook_event_name, or its tool_input is not an object.
        """
        try:
            data = json.loads(text)
        except ValueError as e:
            raise HookError(f"the hook payload is not JSON: {e}") from e
        if not isinstance(data, dict) or not isinstance(data.get("hook_event_name"), str):
            raise HookError("the hook payload has no hook_event_name")
        tool_input = data.get("tool_input", {})
        if data["hook_event_name"] == "UserPromptSubmit":  # the prompt is the input of this event
            tool_input = {"prompt": str(data.get("prompt") or "")}
        if data["hook_event_name"] == "Stop":  # true when Claude Code goes on because a Stop hook blocked once
            tool_input = {"stop_hook_active": bool(data.get("stop_hook_active"))}
        if not isinstance(tool_input, dict):
            raise HookError("tool_input of the hook payload is not an object")
        return Event(data["hook_event_name"], str(data.get("tool_name") or ""), tool_input,
                     str(data.get("session_id") or ""), str(data.get("cwd") or ""), data.get("tool_response"))

    @staticmethod
    def write(event: Event, verdict: Verdict, notes: Sequence[str] = ()) -> str:
        """What Claude Code reads back for a verdict on an event.

        Args:
            event: the hook call judged.
            verdict: the rules' verdict on it.
            notes: the notes of the act step for the model (an approval, a delivery), one per line.

        Returns:
            JSON text: {"decision": "block", reason} for a refused Stop; hookSpecificOutput with permissionDecision
            and its reason for a PreToolUse that asks or refuses; else hookSpecificOutput with additionalContext (the
            notes) when there are notes; "" (nothing said) otherwise.
        """
        if event.kind == "Stop" and refused(verdict):  # the turn does not end: Claude Code reads why and goes on
            return json.dumps({"decision": "block", "reason": verdict.reason}, ensure_ascii=False)
        if event.kind == DECIDES and verdict.decision in CLAUDE_DECISION:
            out = {"hookEventName": event.kind, "permissionDecision": CLAUDE_DECISION[verdict.decision],
                   "permissionDecisionReason": verdict.reason}
        elif notes:
            out = {"hookEventName": event.kind, "additionalContext": "\n".join(notes)}
        else:
            return ""
        return json.dumps({"hookSpecificOutput": out}, ensure_ascii=False)
