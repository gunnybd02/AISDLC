"""The user's word on a git command the rules ask about (a protected branch: the git rules P1-P8, gear/detect/git.py).
The git block of the MCP server gives the form question; the user's approval word to it, read from the PostToolUse of
AskUserQuestion, is kept in pl_asks under the command's code, unused; the next run of exactly that command uses it up
(used = 1), and every run of the block is kept in pl_git_runs. One approval, one run."""
import hashlib
import json
import re
import time
import uuid

from harness.utils.contracts import YES

QUESTION = re.compile("^Duyệt git (?P<command>.+) trong (?P<repo>.+) \\[(?P<code>g[0-9a-f]{12})\\]\\?$")
ACCEPTED = "GATE: the user accepted git {command} [{code}]; run it now with run('git', 'run', ...), once."


def code_of(repo, words):
    """The code of exactly this command in exactly this repository."""
    return "g" + hashlib.sha256(json.dumps([str(repo), list(words)]).encode("utf-8")).hexdigest()[:12]


def question(repo, words, why):
    """What the model asks the user, for the git command words in repo the rules ask about for why."""
    q = f"Duyệt git {' '.join(words)} trong {repo} [{code_of(repo, words)}]?"
    return (f"The git rules ask the user first: {why}. Ask now with AskUserQuestion, one question, exactly: {q} "
            f"Options: \"{YES}\", \"Không\". Never fill in the answer. When the user accepts, run the same "
            f"command again.")


def accepts(port, answers):
    """Keep the user's approval of each git question answered with the approval word; the notes for the model."""
    notes = []
    for q, label in (answers or {}).items():
        m = QUESTION.match(str(q))
        if not m or str(label).strip() != YES:
            continue
        port.write(lambda con, rec, code=m["code"]: con.execute(
            "INSERT OR REPLACE INTO pl_asks (sid, key, at, used) VALUES ('', ?, ?, 0)", (code, int(time.time() * 1000))))
        notes.append(ACCEPTED.format(command=m["command"], code=m["code"]))
    return notes


def take(port, code):
    """Use up the user's approval of the command code: True when there was one, unused."""
    if not port.rows("SELECT 1 FROM pl_asks WHERE sid = '' AND key = ? AND used = 0", (code,)):
        return False
    port.write(lambda con, rec: con.execute("UPDATE pl_asks SET used = 1 WHERE sid = '' AND key = ?", (code,)))
    return True


def keep_run(port, repo, words, code, reason, exit_code):
    port.write(lambda con, rec: con.execute(
        "INSERT INTO pl_git_runs (uid, sid, source, tool, step, ok, exit, reason, command, linked_to, at) VALUES "
        "(?, '', 'mcp', 'git.run', '', ?, ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, int(exit_code == 0), exit_code, reason, json.dumps({"repo": str(repo), "args": list(words)}),
         code, int(time.time() * 1000))))
