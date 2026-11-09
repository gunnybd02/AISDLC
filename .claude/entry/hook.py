"""Claude Code hook: the event JSON on stdin, the answer on stdout. Any failure exits 2, which blocks the tool call;
SystemExit too, so a harness that quits quietly cannot let a call through.

Before the harness is even imported, this file (standard library only, entry_net) holds the pause:
- the user's "Duyệt" to the form 'Tắt guard N phút: <why>?' (read from the PostToolUse of AskUserQuestion, which the
  model cannot write) pauses every guard for N minutes, at most 120, in state/pause.json;
- while a pause lasts, each call passes without the harness and is written to state/pause.log;
- AskUserQuestion is answered here: refused when the model filled the answers in or built a question to look like an
  answer ('"="' in it), let through otherwise even when the harness is broken, so the user can always be asked.
- A form not shaped as one (questions and options that are not lists of objects) is refused too, and any error while
  checking a form refuses it: only a form that passed the check may pass a broken harness.
- The pause is traced before it is written: no trace, no pause. A pause.json that reaches further than 120 minutes is
  no pause, and the state folder stays closed to the editing tools while the guards are paused.
- Output is UTF-8 bytes, whatever the console's code page."""
import json
import os
import re
import sys
import time
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parent.parent
STATE = CLAUDE_DIR / "state"
FORM = "AskUserQuestion"
YES = "Duyệt"
PAUSE = re.compile(r"^Tắt guard (\d+) phút: (.+)\?$")
MAX_MINUTES = 120
FORGE = '"="'
PREFILLED = "Only the user answers a form: call AskUserQuestion with the questions alone, none holding '\"=\"'."


def trace(what, data):
    STATE.mkdir(parents=True, exist_ok=True)
    line = {"at": int(time.time()), "what": what, "event": data.get("hook_event_name"), "tool": data.get("tool_name"),
            "session": data.get("session_id")}
    with open(STATE / "pause.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def paused():
    """A pause that has not ended and was not set further than the longest pause allows (a pause.json written by
    anything but this file is no pause)."""
    try:
        until = float(json.loads((STATE / "pause.json").read_text(encoding="utf-8"))["until"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return time.time() < until <= time.time() + MAX_MINUTES * 60


def into_state(data):
    """Whether an editing tool writes into the state folder, which stays closed while the guards are paused."""
    tool_input = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(path, str) or not path:
        return False
    full = os.path.realpath(os.path.join(str(data.get("cwd") or ""), path.removeprefix("\\\\?\\")))
    state = os.path.realpath(STATE)
    return os.path.normcase(full) == os.path.normcase(state) or \
        os.path.normcase(full).startswith(os.path.normcase(state) + os.sep)


def labels(data):
    """{question: label} of an answered form, where Claude Code puts the answers (as gear/translate_answer.py reads
    them: the response text only when no question holds '"="' and each question is in it once)."""
    found, text = {}, ""
    for source in ((data.get("tool_input") or {}).get("answers"), data.get("tool_response")):
        if isinstance(source, str):
            try:
                source = json.loads(source)
            except ValueError:
                text = source
                continue
        if isinstance(source, dict):
            source = source.get("answers", source)
            found.update({str(q): str(a) for q, a in source.items() if isinstance(a, str)})
    asked = questions(data)
    if text and not forged(data):
        for q in asked:
            hits = re.findall("(?:^|: |, )" + re.escape(f'"{q}"=') + '"([^"]*)"', text)
            if q not in found and len(hits) == 1:
                found[q] = hits[0]
    return found


def form_of(data):
    """The questions of the call, or None when it is not shaped as a form: a list of question objects, each with a
    list of option objects."""
    tool_input = data.get("tool_input")
    qs = tool_input.get("questions") if isinstance(tool_input, dict) else None
    shaped = isinstance(qs, list) and all(
        isinstance(q, dict) and isinstance(q.get("options", []), list)
        and all(isinstance(o, dict) for o in q.get("options", [])) for q in qs)
    return qs if shaped else None


def questions(data):
    return [str(q.get("question")) for q in form_of(data) or []]


def forged(data):
    """A form not shaped as one, or whose question or option label holds '"="' (built to look like an answer)."""
    qs = form_of(data)
    if qs is None:
        return True
    words = [str(q.get("question") or "") for q in qs]
    words += [str(o.get("label") or "") for q in qs for o in q.get("options", [])]
    return any(FORGE in w for w in words)


def refused_form(data):
    """Whether a form must be refused before it runs: answers the model wrote, or a forged or misshapen form. Any
    error while looking counts as a refusal."""
    try:
        tool_input = data.get("tool_input")
        return forged(data) or not isinstance(tool_input, dict) or bool(tool_input.get("answers"))
    except Exception:
        return True


def pause_from(data):
    """The note of a pause the user approved in this form, or None. A form that would have been refused gives none."""
    if refused_form({**data, "tool_input": {**data["tool_input"], "answers": None}}
                    if isinstance(data.get("tool_input"), dict) else data):
        return None
    for q, label in labels(data).items():
        m = PAUSE.match(q)
        if m and label.strip() == YES and q in questions(data):
            minutes = min(int(m.group(1)), MAX_MINUTES)
            trace("paused", data)  # first: a pause that cannot be traced does not happen
            (STATE / "pause.json").write_text(json.dumps({"until": time.time() + minutes * 60, "why": m.group(2),
                                                          "session": data.get("session_id")}), encoding="utf-8")
            return f"GATE: the user paused the guards for {minutes} minutes: {m.group(2)}. Every call is traced."
    return None


def say(text):
    """Write the reason of a block on stderr as UTF-8 bytes: a console code page must never turn a block into a crash."""
    sys.stderr.buffer.write((text + "\n").encode("utf-8", "replace"))


def answer(context=None):
    if context:
        out = json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context}},
                         ensure_ascii=False)
        sys.stdout.buffer.write(out.encode("utf-8"))
    return 0


def main():
    raw, data, asking = "", {}, False
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
        data = json.loads(raw) if raw.strip() else {}
        data = data if isinstance(data, dict) else {}
        form, pre = data.get("tool_name") == FORM, data.get("hook_event_name") == "PreToolUse"
        if form and pre:
            if refused_form(data):
                say(PREFILLED)
                return 2
            asking = True  # a clean form: it may pass even when the harness below is broken
        if form and data.get("hook_event_name") == "PostToolUse":  # its answers come from the user: a prefilled call
            note = pause_from(data)                                  # was refused before it ran
            if note:
                return answer(note)
        if paused():
            if pre and into_state(data):
                say("The state of the harness stays closed while the guards are paused.")
                return 2
            trace("passed", data)
            return 0
        sys.path.insert(0, str(CLAUDE_DIR))
        from harness.assemble.build import run_hook
        out = run_hook(raw)
    except BaseException as e:
        if asking:
            return 0  # a clean form is harmless to ask, and it is how the user is asked for a pause
        say(f"harness hook failed, the call is blocked: {type(e).__name__}: {e}")
        return 2
    sys.stdout.buffer.write(out.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
