"""git: run a git command through the harness. The command is judged by the same rules as a shell line (the git rules
P1-P8 ask about a protected branch only). Nothing to ask: it runs. Asked: the user's word comes first, in a form, kept
in SQL; the next run of exactly that command uses it up. Refused (git commit: step_done): it never runs. Every run is
kept in pl_git_runs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.mcp.actions.ledger import store_note
from harness.utils.contracts import ActionContext, ActionError, McpAction, WRITE, asked, refused, session_of
from harness.utils.git.asks import code_of, keep_run, question, take
from harness.utils.git.run import run_git
from harness.utils.plan.ship import git_commit, git_push

ACTIONS = [("git.run", "Run"), ("git.commit", "Commit"), ("git.push", "Push")]
TAIL = 4000


class Run(McpAction):
    """git.run: one git command in a repository, judged as a shell line, kept in pl_git_runs."""
    block, name, effect = "git", "run", WRITE
    summary = ("Run one git command in a repository (args: the words after git); on a protected branch the user "
               "accepts it first in a form, and every run is kept in SQL")
    args_schema = {"type": "object", "properties": {"repo": {"type": "string"}, "args": {"type": "array"}},
                   "required": ["repo", "args"]}
    needs = ("git_judge", "ledger")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Run git <args> in repo when the rules let it (a refusal raises ActionError; an ask with no word of the user
        kept answers the form question); answer "git <args>: exit <code>" and the tail of git's output."""
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


class Commit(McpAction):
    """git.commit: named files of the session's plan, committed by the harness."""
    block, name, effect = "git", "commit", WRITE
    summary = ("Commit named files of the session's plan (paths from its root): not on a protected branch, only files the "
               "plan allows, code verified green, judged by the commit guards; then step_done ends the step")
    args_schema = {"type": "object", "properties": {"files": {"type": "array"}, "message": {"type": "string"}},
                   "required": ["files", "message"]}
    needs = ("plans", "session", "commit_judge")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Commit the named files of the session's plan (utils/plan/ship.git_commit); answer what was committed."""
        return git_commit(ctx.ports["plans"], session_of(ctx), args["files"], args["message"], ctx.ports["commit_judge"])


class Push(McpAction):
    """git.push: the branch of the session's unit plan, pushed to origin in deliver."""
    block, name, effect = "git", "push", WRITE
    summary = ("Push the branch of the session's unit plan to origin, in Deliver: never the home, never a protected "
               "branch; judged like git push in a shell and kept in pl_git_audit")
    needs = ("plans", "session", "git_judge", "store")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Push the branch of the session's unit plan to origin (utils/plan/ship.git_push); answer what was pushed, with
        the store's note."""
        return git_push(ctx.ports["plans"], session_of(ctx), ctx.ports["git_judge"]) + store_note(ctx)
