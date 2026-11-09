"""Answers: the facts of an AskUserQuestion. After the call (PostToolUse) the label the user chose for each question,
read where Claude Code may put it: tool_input.answers, an "answers" object in the response, or the response text
'"<question>"="<label>"'. Before the call (PreToolUse) whether the model filled answers in itself."""
import json

from harness.utils.contracts import Translator

TOOL = "AskUserQuestion"


def questions(event):
    return [str(q.get("question")) for q in event.input.get("questions") or [] if isinstance(q, dict) and q.get("question")]


def given(event):
    """{question: label} as the call or its response carries them."""
    found = {}
    for source in (event.input.get("answers"), event.response):
        if isinstance(source, str):
            try:
                source = json.loads(source)
            except ValueError:
                continue
        if isinstance(source, dict):
            source = source.get("answers", source)
            found.update({str(q): str(a) for q, a in source.items() if isinstance(a, (str, int, float))})
    text = event.response if isinstance(event.response, str) else ""
    for q in questions(event):
        key = f'"{q}"="'
        if q not in found and key in text:
            found[q] = text.split(key, 1)[1].split('"', 1)[0]
    return found


class Answers(Translator):
    def translate(self, event):
        if event.tool != TOOL:
            return {}
        if event.kind == "PreToolUse":
            return {"form_prefilled": sorted(event.input.get("answers") or {})} if event.input.get("answers") else {}
        if event.kind == "PostToolUse":
            return {"answers": given(event)}
        return {}
