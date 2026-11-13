"""PlanGate: the findings of the approval gate.
- write.state: a write into the harness's own state (its ledger, its pause), approved plan or not;
- plan.none: a write while the session has no approved plan;
- plan.outside: a write to a file the approved plan does not name (its files and tests, under its root);
- form.prefilled: an AskUserQuestion whose answers the model filled in itself (only the user answers a form);
- form.forged: an AskUserQuestion with a question built to look like an answer ('"="' in it);
- shell.unread: a shell call the reader cannot see whole, with the agent's words on what it does, the command, the
  files the reader did see and what it could not read: the user is the one to say;
- shell.unexplained: the same call with no words of the agent that explain it (fewer than three words, or the command
  copied back).
Paths are compared as the file system resolves them: real paths (8.3 short names expanded), no \\\\?\\ prefix, case
folded where the system folds it."""
import re

from harness.utils.contracts import Detector, Finding
from harness.utils.plan.files import named, relative

LONGEST_COMMAND = 500  # characters of the command shown in the question; Claude Code shows the whole of it too

class PlanGate(Detector):
    def detect(self, event, facts):
        out = []
        if facts.get("form_prefilled"):
            out.append(Finding("form.prefilled", ", ".join(facts["form_prefilled"])))
        if facts.get("form_forged"):
            out.append(Finding("form.forged", ", ".join(facts["form_forged"])))
        plan, state = facts.get("plan"), facts.get("state_dir")
        for path in facts.get("writes", []):
            if state and relative(path, state) is not None:
                out.append(Finding("write.state", path))
            elif plan is None:
                out.append(Finding("plan.none", path))
            elif relative(path, plan["root"]) not in named(plan):
                out.append(Finding("plan.outside", f"{path} is not a file of plan {plan['plan_id']}"))
        if facts.get("shell_unread"):
            out.append(shell_finding(facts))
        return out


def plain_words(text):
    return re.findall(r"\w+", str(text).lower())


def explained(said, command):
    """Whether the agent said in words of its own what the command does: three words at least, not the command."""
    words = plain_words(said)
    return len(words) >= 3 and " ".join(words) not in " ".join(plain_words(command))


def shell_finding(facts):
    said, command, unread = facts.get("shell_said", ""), facts.get("shell_command", ""), facts["shell_unread"]
    if not explained(said, command):
        return Finding("shell.unexplained", "; ".join(unread))
    shown = command if len(command) <= LONGEST_COMMAND else command[:LONGEST_COMMAND] + "..."
    files = ", ".join(facts.get("writes", [])) or "không file nào"
    return Finding("shell.unread", f'Agent giải thích: "{said.strip()}". Lệnh: {shown}. Harness thấy lệnh ghi: '
                                   f'{files}. Phần harness không đọc được: {"; ".join(unread)}')
