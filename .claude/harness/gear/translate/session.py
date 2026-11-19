"""SessionCalls: a cloud session about to open, as a rule action (kind open_session, op no_model or no_pass); the when
rows session.no_model and session.no_pass refuse it (utils/forge/sessions.py: Sonnet is the default model).

The tool is known by its name, whatever its server is called (mcp__claude-code-remote__create_session, ...). A call on
the default model runs. A call that names no model would open the session on the parent's model: it is refused and
told to name one. A call on another model runs only when the ledger holds the user's pass for exactly it (model, title
and prompt); else the refusal carries the form question in its detail. The port's session_pass (code -> bool) reads
the pass."""
from __future__ import annotations

from typing import Any, Optional

from harness.utils.contracts import RULE_ACTIONS, Event, Translator
from harness.utils.forge import sessions
from harness.utils.shapes import Facts


def act(op: str, detail: str) -> Facts:
    """One rule action of kind open_session.

    Args:
        op: no_model or no_pass.
        detail: what the refusal shows in brackets.

    Returns:
        The facts with the action.
    """
    return {RULE_ACTIONS: [{"kind": "open_session", "op": op, "detail": detail}]}


class SessionCalls(Translator):
    """The rule action of a session the user has not allowed on its model."""
    VOCABULARY = ("kind", "op")
    READS = ("session_pass",)

    def translate(self, event: Event, facts: Optional[Facts] = None) -> Facts:
        """Before a create_session call: no_model when it names none, no_pass on a model other than the default
        without the user's pass; {} for the default model, an allowed call and every other call."""
        if event.kind != "PreToolUse" or not sessions.is_call(event.tool):
            return {}
        model = sessions.model_of(event.input)
        if not model:
            return act("no_model", sessions.DEFAULT_MODEL)
        if sessions.free(model):
            return {}
        held: Any = (facts or {}).get("session_pass")
        if callable(held) and held(sessions.call_code(event.input)):
            return {}
        return act("no_pass", sessions.question(event.input))
