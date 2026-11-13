"""HookIO: the hook JSON of Claude Code becomes an Event, and a verdict becomes what Claude Code reads. Allow says
nothing, so Claude Code's own permissions still apply. Only PreToolUse takes a decision; the notes of the act step
(an approval, a delivery) reach the model as additionalContext when there is no decision to give."""
import json

from harness.utils.contracts import CLAUDE_DECISION, Event

DECIDES = "PreToolUse"


class HookError(ValueError):
    pass


class HookIO:
    @staticmethod
    def read(text):
        try:
            data = json.loads(text)
        except ValueError as e:
            raise HookError(f"the hook payload is not JSON: {e}") from e
        if not isinstance(data, dict) or not isinstance(data.get("hook_event_name"), str):
            raise HookError("the hook payload has no hook_event_name")
        tool_input = data.get("tool_input", {})
        if not isinstance(tool_input, dict):
            raise HookError("tool_input of the hook payload is not an object")
        return Event(data["hook_event_name"], str(data.get("tool_name") or ""), tool_input,
                     str(data.get("session_id") or ""), str(data.get("cwd") or ""), data.get("tool_response"))

    @staticmethod
    def write(event, verdict, notes=()):
        if event.kind == DECIDES and verdict.decision in CLAUDE_DECISION:
            out = {"hookEventName": event.kind, "permissionDecision": CLAUDE_DECISION[verdict.decision],
                   "permissionDecisionReason": verdict.reason}
        elif notes:
            out = {"hookEventName": event.kind, "additionalContext": "\n".join(notes)}
        else:
            return ""
        return json.dumps({"hookSpecificOutput": out}, ensure_ascii=False)
