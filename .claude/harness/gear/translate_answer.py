"""Answers: the facts of an AskUserQuestion.
- Before the call (PreToolUse): whether the model filled answers in itself (form_prefilled), and whether a question or
  an option label is built to look like an answer, with '"="' in it, or the call is not shaped as a form (form_forged).
  A call that is not shaped as a form gives no answer after it either.
- After the call (PostToolUse): the label the user chose for each question, read from tool_input.answers or an
  "answers" object in the response; from the response text '"<question>"="<label>"' only when no question or label
  holds '"="', and each question is found there once, at the start of the text or after ": " or ", "."""
import json
import re

from harness.utils.contracts import Translator

TOOL = "AskUserQuestion"
FORGE = '"="'


def shaped(event):
    """Whether the call has the shape of a form: a list of question objects, each with a list of option objects."""
    qs = event.input.get("questions")
    return isinstance(qs, list) and all(
        isinstance(q, dict) and isinstance(q.get("options", []), list)
        and all(isinstance(o, dict) for o in q.get("options", [])) for q in qs)


def questions(event):
    return [str(q.get("question")) for q in event.input["questions"] if q.get("question")] if shaped(event) else []


def texts(event):
    """Every question and option label of the form: the words the model wrote into it."""
    out = []
    for q in event.input["questions"] if shaped(event) else []:
        out.append(str(q.get("question") or ""))
        out += [str(o.get("label") or "") for o in q.get("options", [])]
    return out


def given(event):
    """{question: label} as the call or its response carries them; nothing for a call that is not shaped as a form."""
    if not shaped(event):
        return {}
    found, text = {}, ""
    for source in (event.input.get("answers"), event.response):
        if isinstance(source, str):
            try:
                source = json.loads(source)
            except ValueError:
                text = source
                continue
        if isinstance(source, dict):
            source = source.get("answers", source)
            found.update({str(q): str(a) for q, a in source.items() if isinstance(a, (str, int, float))})
    asked = questions(event)
    if text and not any(FORGE in t for t in texts(event)):
        for q in asked:
            hits = re.findall("(?:^|: |, )" + re.escape(f'"{q}"=') + '"([^"]*)"', text)
            if q not in found and len(hits) == 1:
                found[q] = hits[0]
    return found


class Answers(Translator):
    def translate(self, event):
        if event.tool != TOOL:
            return {}
        if event.kind == "PreToolUse":
            facts = {}
            answers = event.input.get("answers")
            if answers:
                facts["form_prefilled"] = sorted(map(str, answers)) if isinstance(answers, dict) else ["(answers)"]
            forged = [t for t in texts(event) if FORGE in t] if shaped(event) else ["(not shaped as a form)"]
            if forged:
                facts["form_forged"] = forged
            return facts
        if event.kind == "PostToolUse":
            return {"answers": given(event)}
        return {}
