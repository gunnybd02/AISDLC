"""orchestra, the parent's review and final route (docs/05b-orchestra-cloud.md part 3; utils/orchestra/review.py,
land.py). The parent reads no code: it checks each handed-back child by its receipt and a rerun of its tests,
accepts it as one pull request into its unit's base, or sends it back (3 rounds at most); land merges the pull
requests at the end, the parent resolving conflicts there, and closes the plan as delivered.

- check {name, timeoutMin?}: fetch the child's branch, read its receipt, rerun its tests.
- accept {name}: a green check this round; open its pull request (nothing is merged).
- reject {name, why}: send it back; the answer is the send_message to make.
- answer {name, text}: the reply to a child's question; the answer is the send_message to make.
- forget {name, why}: drop a child that will not come back.
- read {name}: its receipt.
- land {timeoutMin?}: merge every accepted pull request, run each unit's tests, close the plan delivered.
- release {name, why}: give a child's session back to the user (utils/orchestra/cleanup.py).
- remove: one checklist the user ticks, then the archive_session call of each ticked child.
- digest: one line per child."""
from __future__ import annotations

from typing import Any, Callable

from harness.utils.contracts import READ, WRITE, ActionContext, ActionError, McpAction
from harness.utils.git.github import GitHubError
from harness.utils.git.run import GitError
from harness.utils.orchestra import cleanup, land, review
from harness.utils.orchestra.fetch import FetchError

ACTIONS = [("orchestra.check", "Check"), ("orchestra.accept", "Accept"), ("orchestra.reject", "Reject"),
           ("orchestra.answer", "Answer"), ("orchestra.forget", "Forget"), ("orchestra.read", "Read"),
           ("orchestra.land", "Land"), ("orchestra.release", "Release"), ("orchestra.remove", "Remove"),
           ("orchestra.digest", "Digest")]
NAME = {"type": "string", "description": "the child's name, as its card names it"}
MINUTES = {"type": "integer", "description": "minutes each test run may take, 1 to 30 (default 10)"}


def session_of(ctx: ActionContext) -> str:
    """The parent's session.

    Args:
        ctx: the action's ports, with session.

    Returns:
        The Claude Code session id.

    Raises:
        ActionError: no session yet.
    """
    sid = ctx.ports["session"]()
    if not sid:
        raise ActionError("no session: the harness has not seen this session's prompt yet")
    return sid


def parent_run(step: Callable[[], str]) -> str:
    """Run one step of the parent's review, its refusals turned into the action's error.

    Args:
        step: a callable with no argument that returns the answer.

    Returns:
        The step's answer.

    Raises:
        ActionError: the step refused, or git or GitHub failed.
    """
    try:
        return step()
    except (review.ReviewError, FetchError, GitError, GitHubError) as e:
        raise ActionError(str(e)) from e


def units(ctx: ActionContext) -> dict[str, Any]:
    """The declared units by name, {} when the port is not there.

    Args:
        ctx: the action's ports.

    Returns:
        {name: {repo, path, verify, base}}.
    """
    return ctx.ports.get("units", dict)()


class Check(McpAction):
    """orchestra.check: a handed-back child checked by its receipt and a rerun of its tests."""
    block, name, effect = "orchestra", "check", WRITE
    summary = ("Check a child that handed back: fetch its branch, read its receipt, count its AC behaviours, rerun "
               "its tests with its unit's command; green lets accept go")
    args_schema = {"type": "object", "properties": {"name": NAME, "timeoutMin": MINUTES}, "required": ["name"]}
    needs = ("plans", "session", "units", "verify_command")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Check the child (utils/orchestra/review.check) and keep the result on its crew entry."""
        sid = session_of(ctx)
        return parent_run(lambda: review.check(ctx.ports["plans"], sid, args["name"], units(ctx),
                                               list(ctx.ports["verify_command"]()), args.get("timeoutMin", 10)))


class Accept(McpAction):
    """orchestra.accept: open the child's pull request into its unit's base."""
    block, name, effect = "orchestra", "accept", WRITE
    summary = "Accept a child whose check is green this round: one pull request from its branch into its unit's base"
    args_schema = {"type": "object", "properties": {"name": NAME}, "required": ["name"]}
    needs = ("plans", "session", "units", "github")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Open the child's pull request (utils/orchestra/review.accept); nothing is merged."""
        sid = session_of(ctx)
        return parent_run(lambda: review.accept(ctx.ports["plans"], sid, args["name"], units(ctx),
                                                ctx.ports["github"]))


class Reject(McpAction):
    """orchestra.reject: send a child back, one round of 3."""
    block, name, effect = "orchestra", "reject", WRITE
    summary = "Send a child back with why (3 rounds at most); the answer is the send_message to make"
    args_schema = {"type": "object", "properties": {"name": NAME, "why": {"type": "string"}},
                   "required": ["name", "why"]}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Record the send-back (utils/orchestra/review.reject)."""
        sid = session_of(ctx)
        return parent_run(lambda: review.reject(ctx.ports["plans"], sid, args["name"], args["why"]))


class Answer(McpAction):
    """orchestra.answer: the reply to a child's question."""
    block, name, effect = "orchestra", "answer", WRITE
    summary = "Answer a child's question; the answer is the send_message to make"
    args_schema = {"type": "object", "properties": {"name": NAME, "text": {"type": "string"}},
                   "required": ["name", "text"]}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Record the reply (utils/orchestra/review.answer)."""
        sid = session_of(ctx)
        return parent_run(lambda: review.answer(ctx.ports["plans"], sid, args["name"], args["text"]))


class Forget(McpAction):
    """orchestra.forget: drop a child that will not come back."""
    block, name, effect = "orchestra", "forget", WRITE
    summary = "Drop a child that will not come back, with why; its card may be spawned again"
    args_schema = {"type": "object", "properties": {"name": NAME, "why": {"type": "string"}},
                   "required": ["name", "why"]}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Forget the child (utils/orchestra/review.forget)."""
        sid = session_of(ctx)
        return parent_run(lambda: review.forget(ctx.ports["plans"], sid, args["name"], args["why"]))


class Read(McpAction):
    """orchestra.read: a child's receipt, from its branch."""
    block, name, effect = "orchestra", "read", READ
    summary = "Read a child's receipt from its branch"
    args_schema = {"type": "object", "properties": {"name": NAME}, "required": ["name"]}
    needs = ("plans", "session", "units")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """The child's receipt (utils/orchestra/review.read)."""
        sid = session_of(ctx)
        return parent_run(lambda: review.read(ctx.ports["plans"], sid, args["name"], units(ctx)))


class Land(McpAction):
    """orchestra.land: the final route."""
    block, name, effect = "orchestra", "land", WRITE
    summary = ("When every child has ended: merge each accepted pull request (a conflict stops it, for the parent to "
               "resolve), run each unit's tests on its merged base, close the plan delivered")
    args_schema = {"type": "object", "properties": {"timeoutMin": MINUTES}}
    needs = ("plans", "session", "units", "verify_command", "github")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Merge, test and close (utils/orchestra/land.land)."""
        sid = session_of(ctx)
        return parent_run(lambda: land.land(ctx.ports["plans"], sid, units(ctx), list(ctx.ports["verify_command"]()),
                                            ctx.ports["github"], args.get("timeoutMin", 10)))


class Release(McpAction):
    """orchestra.release: a child's session given back to the user."""
    block, name, effect = "orchestra", "release", WRITE
    summary = "Give a child's session back to the user, with why; it leaves the crew and keeps its own work"
    args_schema = {"type": "object", "properties": {"name": NAME, "why": {"type": "string"}},
                   "required": ["name", "why"]}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Release the child (utils/orchestra/cleanup.release)."""
        sid = session_of(ctx)
        return parent_run(lambda: cleanup.release(ctx.ports["plans"], sid, args["name"], args["why"]))


class Remove(McpAction):
    """orchestra.remove: the user's checklist of child sessions to archive, then the archive calls."""
    block, name, effect = "orchestra", "remove", WRITE
    summary = ("Archive finished child sessions: the first call gives one checklist to ask the user; after the "
               "user ticks, the next call removes exactly those and gives each archive_session call")
    args_schema = {"type": "object", "properties": {}}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """The checklist, or the removal of the ticked children (utils/orchestra/cleanup.remove)."""
        sid = session_of(ctx)
        return parent_run(lambda: cleanup.remove(ctx.ports["plans"], sid))


class Digest(McpAction):
    """orchestra.digest: one line per child."""
    block, name, effect = "orchestra", "digest", READ
    summary = "One line per child: state, rounds, session, branch, last check, pull request, merged"
    args_schema = {"type": "object", "properties": {}}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """The digest of the session's delegated plan (utils/orchestra/cleanup.digest)."""
        return cleanup.digest(ctx.ports["plans"], session_of(ctx))
