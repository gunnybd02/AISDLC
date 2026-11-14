"""PlanFiles: the files a call writes, against the approved plan and the harness's state.
- write.state: a write into the harness's own state (its ledger, its maint grant), approved plan or not;
- plan.outside: a write to a file the approved plan does not allow (its file and test patterns, its add file
  grants; a drop grant refuses), under its root;
- read.state: a call that names a place in the harness's own state, read or written by any tool (the shell, Read,
  Grep, Glob...): the ledger is read only through run('ledger', 'db_query');
- shell.unread: a shell call the reader cannot see whole, with the agent's words on what it does, the command, the
  files the reader did see and what it could not read: the user is the one to say;
- shell.unexplained: the same call with no words of the agent that explain it (fewer than three words, or the command
  copied back).
A write with no approved plan is tracked.py's (plan.none). Paths are compared as utils/plan/files.py resolves them."""
import re

from harness.utils.contracts import Detector, Finding
from harness.utils.plan.files import allows, holds, relative

LONGEST_COMMAND = 500  # characters of the command shown in the question; Claude Code shows the whole of it too


def in_state(path, state):
    return bool(state) and relative(path, state) is not None


class PlanFiles(Detector):
    @staticmethod
    def allowed(plan, path):
        """Whether the plan allows the write: a path under its root its patterns or grants allow (utils/plan/files.py),
        or a folder above a planned file (a mkdir of it)."""
        rel = relative(path, plan["root"])
        return rel is not None and (allows(plan, rel) or holds(plan, rel))

    def detect(self, event, facts):
        out = []
        plan, state = facts.get("plan"), facts.get("state_dir")
        for path in facts.get("writes", []):
            if in_state(path, state):
                out.append(Finding("write.state", path))
            elif plan is not None and not self.allowed(plan, path):
                out.append(Finding("plan.outside", f"{path} is not a file of plan {plan['plan_id']}"))
        written = set(facts.get("writes", []))
        for path in facts.get("mentions", []):
            if path not in written and in_state(path, state):
                out.append(Finding("read.state", path))
                break
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
    files = ", ".join(facts.get("writes", [])) or "kh\u00f4ng file n\u00e0o"
    return Finding("shell.unread", f'Agent gi\u1ea3i th\u00edch: "{said.strip()}". L\u1ec7nh: {shown}. Harness th\u1ea5y l\u1ec7nh ghi: '
                                   f'{files}. Ph\u1ea7n harness kh\u00f4ng \u0111\u1ecdc \u0111\u01b0\u1ee3c: {"; ".join(unread)}')
