"""git: run a git command through the harness. The command is judged by the same rules as a shell line (the git rules
P1-P8 ask about a protected branch only). Nothing to ask: it runs. Asked: the user's word comes first, in a form, kept
in SQL; the next run of exactly that command uses it up. Refused (git commit: step_done): it never runs. Every run is
kept in pl_git_runs."""
from pathlib import Path

from harness.utils.contracts import WRITE, ActionError, McpAction, asked, refused
from harness.utils.git.asks import code_of, keep_run, question, take
from harness.utils.git.run import run_git

ACTIONS = [("git.run", "Run")]
TAIL = 4000


class Run(McpAction):
    block, name, effect = "git", "run", WRITE
    summary = ("Run one git command in a repository (args: the words after git); on a protected branch the user "
               "accepts it first in a form, and every run is kept in SQL")
    args_schema = {"type": "object", "properties": {"repo": {"type": "string"}, "args": {"type": "array"}},
                   "required": ["repo", "args"]}
    needs = ("git_judge", "ledger")

    def run(self, ctx, args):
        repo, words = args["repo"], args["args"]
        if not words or not all(isinstance(w, str) and w for w in words) or words[0] == "git":
            raise ActionError("args are the words after git, each a non-empty string: ['push', 'origin', 'work']")
        if not Path(repo).is_dir():
            raise ActionError(f"{repo} is not a folder")
        verdict = ctx.ports["git_judge"](repo, words)
        if refused(verdict):
            raise ActionError(verdict.reason)
        reason, code = ", ".join(f.kind for f in verdict.findings), code_of(repo, words)
        if asked(verdict) and not take(ctx.ports["ledger"], code):
            return question(repo, words, verdict.reason)
        exit_code, output = run_git(repo, words)
        keep_run(ctx.ports["ledger"], repo, words, code, reason, exit_code)
        head = f"git {' '.join(words)}: exit {exit_code}" + (" (accepted by the user)" if asked(verdict) else "")
        return head + ("\n" + output[-TAIL:] if output.strip() else "")
