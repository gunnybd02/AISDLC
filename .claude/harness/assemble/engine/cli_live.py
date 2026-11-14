"""live status | live publish | live update (docs: blue/green release). publish builds a release of the work tree's
code, runs its own doctor (every check of a start: loader, names, argument types, ports, effects, rules, nets) and puts
it in force only with the user's word: a one-use pass of exactly that sha, given by the answer Cho ph\u00e9p to the
form question 'Cho ph\u00e9p ph\u00e1t h\u00e0nh harness <sha>?' (a session cannot answer a form; utils/git/asks.py
keeps the pass).
update brings the newest main of the harness's own clone into a running session: it pins the code that runs now when
no release is in force (so the new code is not run before the user's word), fast-forwards the clone (utils/git/pull.py)
and publishes as above. Hooks run the new release at their next call, MCP servers at their next request."""
from harness.assemble.engine.live_mcp import healthy
from harness.utils.gateway.release import ALLOW_LABEL, NO_LABEL, build, current, publish, release_dir, stamp
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
        return 1, f"refused: the doctor of release {sha} finds problems; run python3 entry/doctor.py and fix them"
    if not take(port, f"live-publish:{sha}"):
        q = f"{ALLOW_LABEL} ph\u00e1t h\u00e0nh harness {sha}?"
        return 0, (f"Release {sha} is built and its doctor is clean. Publishing needs the user's word: ask with "
                   f"AskUserQuestion, one question, exactly: {q} Options: \"{ALLOW_LABEL}\", \"{NO_LABEL}\". Never "
                   f"fill in the answer. Then run live publish again.")
    publish(home, sha)
    return 0, f"Release {sha} is in force: hooks run it at once, MCP servers at their next call."


def update_door(port, home):
    """(exit code, text): 0 up to date, asked or published; 1 refused."""
    pinned = ""
    if current(home) is None:  # what runs now is the work tree: pin it before the clone changes under it
        sha = build(home)
        publish(home, sha)
        pinned = f"Pinned the code that runs now as release {sha}. "
    try:
        before, after = fast_forward(home)
    except PullError as e:
        return 1, f"{pinned}refused: {e}"
    if before == after and stamp(home) == current(home):
        return 0, f"{pinned}Up to date: main {after[:12]} is the release in force."
    code, text = publish_door(port, home)
    news = f"main {before[:12]} -> {after[:12]}. " if before != after else ""
    return code, pinned + news + text
