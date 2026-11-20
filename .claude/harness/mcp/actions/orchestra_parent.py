"""orchestra, the parent's review and final route (docs/05b-orchestra-cloud.md part 3; utils/orchestra/review.py,
land.py). The parent reads no code: it checks each handed-back child by the project's CI and a rerun of its own
acceptance tests, merges it into its base when green (accept), or sends it back (limits.rounds at most); close ends the
plan as delivered when every child is merged or forgotten.

- check {name, timeoutMin?}: fetch the child's branch, read its receipt, rerun its tests.
- accept {name}: a green check this round; open its pull request (nothing is merged).
- reject {name, why}: send it back: a send-back note on its branch, then spawn opens a fresh session of it.
- answer {name, text}: the reply to a child's question: an answer note on its branch, then a fresh session.
- forget {name, why}: drop a child that will not come back.
- read {name}: its receipt.
- close: every child merged or forgotten, its ledger copy in the store: the plan is delivered (no form 2).
- release {name, why}: give a child's session back to the user (utils/orchestra/cleanup.py).
- remove: one checklist the user ticks, then the archive_session call of each ticked child.
- digest: one line per child.
- doorbell: after a CI result woke the parent, each child's CI result, failed rules and new comments, read on GitHub,
  recorded, with its next step (utils/orchestra/doorbell.py)."""
from __future__ import annotations

from typing import Any, Callable

from harness.utils.contracts import ActionContext, ActionError, McpAction, READ, WRITE, answered, session_of
from harness.utils.git.github import GitHubError
from harness.utils.git.run import GitError
from harness.utils.orchestra import cleanup, doorbell, land, orders, review
from harness.utils.orchestra.card import in_force, plan_units
from harness.utils.plan.item_checks import run_limits
from harness.utils.orchestra.fetch import FetchError

ACTIONS = [("orchestra.check", "Check"), ("orchestra.accept", "Accept"), ("orchestra.reject", "Reject"),
           ("orchestra.answer", "Answer"), ("orchestra.forget", "Forget"), ("orchestra.read", "Read"),
           ("orchestra.close", "Close"), ("orchestra.release", "Release"), ("orchestra.remove", "Remove"),
           ("orchestra.digest", "Digest"), ("orchestra.doorbell", "Doorbell")]
PARENT_ERRORS = (review.ReviewError, FetchError, GitError, GitHubError)  # the refusals of its steps, answered as the action's error
NAME = {"type": "string", "description": "the child's name, as its card names it"}
MINUTES = {"type": "integer", "description": "minutes each test run may take, 1 to 30 (default 10)"}


def store_folder(ctx: ActionContext) -> str:
    """The store's Drive folder id, "" when none is set.

    Args:
        ctx: the action's ports.

    Returns:
        The folder id, or "".
    """
    return str(ctx.ports["store"]() or "")


def units(ctx: ActionContext) -> dict[str, Any]:
    """The units by name: the declared ones and the repos of the plan in force in the calling session.

    Args:
        ctx: the action's ports.

    Returns:
        {name: {repo, path, verify, base}}.
    """
    return plan_units(in_force(ctx.ports["plans"], session_of(ctx)), ctx.ports["units"]())


class Check(McpAction):
    """orchestra.check: a handed-back child checked by its receipt and a rerun of its tests."""
    block, name, effect = "orchestra", "check", WRITE
    summary = ("Check a child that handed back: read its handback comment (the receipt), fetch its branch, count its "
               "AC behaviours, rerun its tests with its unit's command; green lets accept go")
    args_schema = {"type": "object", "properties": {"name": NAME, "timeoutMin": MINUTES}, "required": ["name"]}
    needs = ("plans", "session", "units", "verify_command", "github")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Check the child (utils/orchestra/review.check) and keep the result on its crew entry."""
        sid = session_of(ctx)
        return answered(PARENT_ERRORS, lambda: review.check(ctx.ports["plans"], sid, args["name"], units(ctx),
                                               list(ctx.ports["verify_command"]()), ctx.ports["github"],
                                               args.get("timeoutMin", 10)))


class Accept(McpAction):
    """orchestra.accept: merge the child's pull request at the commit the check tested."""
    block, name, effect = "orchestra", "accept", WRITE
    summary = ("Accept a child whose check is green this round: merge its pull request into its base at the tested "
               "commit, then the stop order")
    args_schema = {"type": "object", "properties": {"name": NAME}, "required": ["name"]}
    needs = ("plans", "session", "units", "github")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Merge the child's pull request (utils/orchestra/land.accept)."""
        sid = session_of(ctx)
        return answered(PARENT_ERRORS, lambda: land.accept(ctx.ports["plans"], sid, args["name"], units(ctx),
                                                ctx.ports["github"]))


def with_order(done: str, ctx: ActionContext, name: str, kind: str, body: str) -> str:
    """The answer of reject or answer, and then the signed order that tells the running child (utils/orchestra/orders.py).

    Args:
        done: the answer of the step (the comment is posted).
        ctx: the action's context.
        name: the child's name.
        kind: fix or answer.
        body: the reason or the answer.

    Returns:
        done, then the order's call when the child takes orders.
    """
    entry = ((ctx.ports["plans"].ticket(session_of(ctx)) or {}).get("crew") or {}).get(name) or {}
    url = (entry.get("fresh") or {}).get("url")  # the comment of the same words on the child's draft
    order = orders.give(ctx.ports["plans"], session_of(ctx), name, kind, f"{body} (the comment: {url})" if url else body)
    soon = f"\n{doorbell.later()}" if doorbell.no_ci(ctx.ports["plans"], session_of(ctx), name) else ""
    if not order:
        return done + soon
    note, cut, _ = done.partition("; nothing is sent to the child")  # review.fresh_session's words for a fresh session
    return (f"{note}.\n{order}" if cut else f"{done}\n{order}") + soon


class Reject(McpAction):
    """orchestra.reject: send a child back, one round of limits.rounds."""
    block, name, effect = "orchestra", "reject", WRITE
    summary = ("Send a child back with why (limits.rounds at most): a comment on its draft and a signed order for its "
               "running session (or spawn opens a fresh one)")
    args_schema = {"type": "object", "properties": {"name": NAME, "why": {"type": "string"}},
                   "required": ["name", "why"]}
    needs = ("plans", "session", "limits", "github")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Post the send-back comment and keep the round (utils/orchestra/review.reject)."""
        sid = session_of(ctx)
        rounds = run_limits(in_force(ctx.ports["plans"], sid), ctx.ports["limits"]())["rounds"]
        return answered(PARENT_ERRORS, lambda: with_order(review.reject(
            ctx.ports["plans"], sid, args["name"], args["why"], rounds, ctx.ports["github"]), ctx, args["name"], "fix",
            args["why"]))


class Answer(McpAction):
    """orchestra.answer: the reply to a child's question."""
    block, name, effect = "orchestra", "answer", WRITE
    summary = ("Answer a child's question: a comment on its draft and a signed order for its running session (or "
               "spawn opens a fresh one)")
    args_schema = {"type": "object", "properties": {"name": NAME, "text": {"type": "string"}},
                   "required": ["name", "text"]}
    needs = ("plans", "session", "github")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Post the answer comment (utils/orchestra/review.answer)."""
        sid = session_of(ctx)
        return answered(PARENT_ERRORS, lambda: with_order(review.answer(
            ctx.ports["plans"], sid, args["name"], args["text"], ctx.ports["github"]), ctx, args["name"], "answer",
            args["text"]))


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
        return answered(PARENT_ERRORS, lambda: review.forget(ctx.ports["plans"], sid, args["name"], args["why"]))


class Read(McpAction):
    """orchestra.read: a child's receipt, from its handback comment."""
    block, name, effect = "orchestra", "read", READ
    summary = "Read a child's receipt from its handback comment on its draft"
    args_schema = {"type": "object", "properties": {"name": NAME}, "required": ["name"]}
    needs = ("plans", "session", "github")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """The child's receipt (utils/orchestra/review.read)."""
        sid = session_of(ctx)
        return answered(PARENT_ERRORS, lambda: review.read(ctx.ports["plans"], sid, args["name"], ctx.ports["github"]))


class Close(McpAction):
    """orchestra.close: the end of the delegated plan."""
    block, name, effect = "orchestra", "close", WRITE
    summary = ("When every child is merged (accept merges it) or forgotten and its ledger copy is in the store: close "
               "the delegated plan delivered and give each child's archive call")
    args_schema = {"type": "object", "properties": {}}
    needs = ("plans", "session", "store")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """End the plan (utils/orchestra/land.close)."""
        sid = session_of(ctx)
        return answered(PARENT_ERRORS, lambda: land.close(ctx.ports["plans"], sid, store_folder(ctx)))


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
        return answered(PARENT_ERRORS, lambda: cleanup.release(ctx.ports["plans"], sid, args["name"], args["why"]))


class Remove(McpAction):
    """orchestra.remove: the user's checklist of child sessions to archive, then the archive calls."""
    block, name, effect = "orchestra", "remove", WRITE
    summary = ("Archive finished child sessions: the first call gives one checklist to ask the user; after the "
               "user ticks, the next call removes exactly those and gives each archive_session call")
    args_schema = {"type": "object", "properties": {}}
    needs = ("plans", "session", "store")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """The checklist, or the removal of the ticked children (utils/orchestra/cleanup.remove)."""
        sid = session_of(ctx)
        return answered(PARENT_ERRORS, lambda: cleanup.remove(ctx.ports["plans"], sid, store_folder(ctx)))


class Digest(McpAction):
    """orchestra.digest: one line per child."""
    block, name, effect = "orchestra", "digest", READ
    summary = "One line per child: state, rounds, session, branch, last check, pull request, merged"
    args_schema = {"type": "object", "properties": {}}
    needs = ("plans", "session")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """The digest of the session's delegated plan (utils/orchestra/cleanup.digest)."""
        return cleanup.digest(ctx.ports["plans"], session_of(ctx))


class Doorbell(McpAction):
    """orchestra.doorbell: what a CI result that woke the parent means for each child."""
    block, name, effect = "orchestra", "doorbell", WRITE
    summary = ("After a GitHub event woke you: each child's CI result, failed rules and new comments, read on GitHub "
               "by the harness and recorded, with the next step (wait, reject, answer, or check then accept)")
    args_schema = {"type": "object", "properties": {}}
    needs = ("plans", "session", "github")

    def run(self, ctx: ActionContext, args: dict[str, Any]) -> str:
        """Read and record each child's draft (utils/orchestra/doorbell.ring)."""
        sid = session_of(ctx)
        return answered(PARENT_ERRORS, lambda: doorbell.ring(ctx.ports["plans"], sid, ctx.ports["github"]))
