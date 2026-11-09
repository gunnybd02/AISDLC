"""Claude Code hook: the event JSON on stdin, the answer on stdout. Any failure exits 2, which blocks the tool call;
SystemExit too, so a harness that quits quietly cannot let a call through.

Before the harness is even imported, this file (standard library only, entry_net) holds the pause:
- the user's "Duyệt" to the form 'Tắt guard N phút: <why>?' (read from the PostToolUse of AskUserQuestion, which the
  model cannot write) pauses every guard for N minutes, at most 120, in state/pause.json;
- while a pause lasts, each call passes without the harness and is written to state/pause.log;
- AskUserQuestion is answered here: refused when the model filled the answers in, let through otherwise even when the
  harness is broken, so the user can always be asked for a pause."""
import json
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
PREFILLED = "Only the user answers a form: call AskUserQuestion with the questions alone."


def trace(what, data):
    STATE.mkdir(parents=True, exist_ok=True)
    line = {"at": int(time.time()), "what": what, "event": data.get("hook_event_name"), "tool": data.get("tool_name"),
            "session": data.get("session_id")}
    with open(STATE / "pause.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def paused():
    try:
        return time.time() < float(json.loads((STATE / "pause.json").read_text(encoding="utf-8"))["until"])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def labels(data):
    """{question: label} of an answered form, where Claude Code puts the answers."""
    found = {}
    for source in ((data.get("tool_input") or {}).get("answers"), data.get("tool_response")):
        if isinstance(source, str):
            try:
                source = json.loads(source)
            except ValueError:
                text = source
                for q in questions(data):
                    if f'"{q}"="' in text:
                        found.setdefault(q, text.split(f'"{q}"="', 1)[1].split('"', 1)[0])
                continue
        if isinstance(source, dict):
            source = source.get("answers", source)
            found.update({str(q): str(a) for q, a in source.items() if isinstance(a, str)})
    return found


def questions(data):
    return [str(q.get("question")) for q in (data.get("tool_input") or {}).get("questions") or [] if isinstance(q, dict)]


def pause_from(data):
    """The note of a pause the user approved in this form, or None."""
    for q, label in labels(data).items():
        m = PAUSE.match(q)
        if m and label.strip() == YES and q in questions(data):
            minutes = min(int(m.group(1)), MAX_MINUTES)
            STATE.mkdir(parents=True, exist_ok=True)
            (STATE / "pause.json").write_text(json.dumps({"until": time.time() + minutes * 60, "why": m.group(2),
                                                          "session": data.get("session_id")}), encoding="utf-8")
            trace("paused", data)
            return f"GATE: the user paused the guards for {minutes} minutes: {m.group(2)}. Every call is traced."
    return None


def answer(context=None):
    if context:
        sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                            "additionalContext": context}}, ensure_ascii=False))
    return 0


def main():
    raw, data = "", {}
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
        data = json.loads(raw) if raw.strip() else {}
        data = data if isinstance(data, dict) else {}
        form, pre = data.get("tool_name") == FORM, data.get("hook_event_name") == "PreToolUse"
        if form and pre and (data.get("tool_input") or {}).get("answers"):
            sys.stderr.write(PREFILLED + "\n")
            return 2
        if form and data.get("hook_event_name") == "PostToolUse":  # its answers come from the user: a prefilled call
            note = pause_from(data)                                  # was refused before it ran
            if note:
                return answer(note)
        if paused():
            trace("passed", data)
            return 0
        sys.path.insert(0, str(CLAUDE_DIR))
        from harness.assemble.build import run_hook
        out = run_hook(raw)
    except BaseException as e:
        if data.get("tool_name") == FORM and data.get("hook_event_name") == "PreToolUse":
            return 0  # asking the user is harmless, and it is how the user is asked for a pause
        sys.stderr.write(f"harness hook failed, the call is blocked: {type(e).__name__}: {e}\n")
        return 2
    sys.stdout.buffer.write(out.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
