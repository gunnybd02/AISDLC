"""live status | live publish | live update (docs: blue/green release). publish builds a release of the work tree's
code, runs its own doctor (every check of a start: loader, names, argument types, ports, effects, rules, nets) and puts
it in force only with the user's word: a one-use pass of exactly that sha, given by the answer Cho ph\u00e9p to the
form question 'Cho ph\u00e9p ph\u00e1t h\u00e0nh harness <sha>?' (a session cannot answer a form; utils/git/asks.py
keeps the pass).
update brings the newest main of the harness's own clone into a running session: it pins the code that runs now when
no release is in force (so the new code is not run before the user's word), fast-forwards the clone (utils/git/pull.py)
and publishes as above. Hooks run the new release at their next call, MCP servers at their next request.
session_update is what Claude Code runs when a session starts (harness/entry/session_start.py, a SessionStart hook): a cloud
machine is prepared ahead of time, so the harness is brought to the newest main then, with the trust of the setup
script that installed it, and put in force when its doctor is clean; otherwise the session keeps what it runs."""
from pathlib import Path

from harness.assemble.engine.live_mcp import healthy
from harness.utils.gateway.release import ALLOW_LABEL, NO_LABEL, anchor, build, current, publish, release_dir, stamp
from harness.utils.git.asks import take
from harness.utils.git.pull import PullError, fast_forward


def status(home):
    running, tree = current(home), stamp(home)
    return (f"In force: {running or 'none (sessions run the work tree)'}. Work tree: {tree}"
            + (" (published)." if running == tree else " (not published)."))


def publish_door(port, home):
    """(exit code, text): 0 published or asked, 1 refused."""
    sha = build(home)
    if current(home) == sha:
        return 0, f"Release {sha} is in force already."
    if not healthy(home, release_dir(home, sha)):
        return 1, f"refused: the doctor of release {sha} finds problems; run its harness/entry/doctor.py and fix them"
    if not take(port, f"live-publish:{sha}"):
        q, boot = f"{ALLOW_LABEL} ph\u00e1t h\u00e0nh harness {sha}?", anchor(home).as_posix()
        return 0, (f"Release {sha} is built and its doctor is clean. Publishing needs the user's word: ask with "
                   f"AskUserQuestion, one question, exactly: {q} Options: \"{ALLOW_LABEL}\", \"{NO_LABEL}\". Never "
                   f"fill in the answer. Then run: python3 \"{boot}\" cli live publish")
    publish(home, sha)
    return 0, f"Release {sha} is in force: hooks run it at once, MCP servers at their next call."


def update_door(port, home):
    """(exit code, text): 0 up to date, asked or published; 1 refused."""
    pinned = pin(home)  # what runs now is the work tree: pin it before the clone changes under it
    try:
        before, after = fast_forward(home)
    except PullError as e:
        return 1, f"{pinned}refused: {e}"
    if before == after and stamp(home) == current(home):
        return 0, f"{pinned}Up to date: main {after[:12]} is the release in force."
    code, text = publish_door(port, home)
    news = f"main {before[:12]} -> {after[:12]}. " if before != after else ""
    return code, pinned + news + text


def pin(home):
    """Put the code that runs now in force when no release is (boot then runs the work tree); the pin text."""
    if current(home) is not None:
        return ""
    sha = build(home)
    publish(home, sha)
    return f"Pinned the code that runs now as release {sha}. "


TOOLS_HINT = (" Its tools: mcp__harness__find, mcp__harness__guide and mcp__harness__run when this session has them. "
              "If it has none, the same from the shell: python3 \"{boot}\" cli tool guide <block> lists a block's "
              "actions, python3 \"{boot}\" cli tool run <block> <action> '<args as JSON>' runs one, python3 \"{boot}\" "
              "cli tool find <words> finds what fits. Read the skill start before any work: guide, name start, mode "
              "skills (from the shell: python3 \"{boot}\" cli tool guide start --mode skills).")


def session_update(home):
    """The text the session reads when it begins: which harness runs and why, and how to reach its tools (Claude Code
    can start before the setup script registers the MCP server, so a session may have none of them)."""
    return harness_update(home) + TOOLS_HINT.format(boot=anchor(home).as_posix())


def harness_update(home):
    """Bring the harness to the newest main of its clone; which harness runs and why."""
    pinned = pin(home)
    try:
        before, after = fast_forward(home)
    except PullError as e:
        return f"{pinned}The harness keeps release {current(home)}: {e}"
    sha = build(home)
    if current(home) == sha:
        return f"{pinned}The harness is up to date: main {after[:12]}, release {sha}."
    if not healthy(home, release_dir(home, sha)):
        return f"{pinned}The harness keeps release {current(home)}: the doctor of main {after[:12]} finds problems."
    publish(home, sha)
    return f"{pinned}The harness was brought up to date: main {before[:12]} -> {after[:12]}, release {sha} in force."
