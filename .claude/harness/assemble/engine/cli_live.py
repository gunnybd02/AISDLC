"""live status | live publish | live update | live hint (docs: blue/green release). publish builds a release of the work tree's
code, runs its own doctor (every check of a start: loader, names, argument types, ports, effects, rules, nets) and puts
it in force only with the user's word: a one-use pass of exactly that sha, given by the answer Allow to the
form question 'Allow publishing harness release <sha>?' (a session cannot answer a form; utils/git/asks.py
keeps the pass).
update brings the newest main of the harness's own clone into a running session: it pins the code that runs now when
no release is in force, fast-forwards the clone (utils/git/pull.py: clean, on main, nothing untracked under harness/)
and puts it in force when its doctor is clean, with no form: main changes only by a pull request the user allowed, so
the merge was the user's word. Hooks run the new release at their next call, MCP servers at their next request.
session_update is what Claude Code runs when a session starts (harness/entry/session_start.py, a SessionStart hook): a cloud
machine is prepared ahead of time, so the harness is brought to the newest main then, with the trust of the setup
script that installed it, and put in force when its doctor is clean; otherwise the session keeps what it runs. The
code that runs then is the one the machine was prepared with: when it put a newer release in force, that release says
how to reach the tools and which skill to read (its door live hint), so the session never reads of a thing it lacks."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from harness.assemble.engine.live_mcp import healthy
from harness.utils.forge.merges import merged  # the one owner of the merge tool's name and answer
from harness.utils.gateway.release import (ALLOW_LABEL, NO_LABEL, anchor, bad, build, current, publish, release_dir,
                                           stamp)
from harness.utils.git.asks import take
from harness.utils.git.pull import PullError, clone_root, fast_forward
from harness.utils.git.run import GitError, git
from harness.utils.shapes import PlanStore


def status(home: str | Path) -> str:
    """Which release is in force and whether the work tree is published (the door live status).

    Args:
        home: the home, the .claude folder of the harness's clone.

    Returns:
        "In force: <sha or none>. Work tree: <stamp> (published|not published)."
    """
    running, tree = current(home), stamp(home)
    return (f"In force: {running or 'none (sessions run the work tree)'}. Work tree: {tree}"
            + (" (published)." if running == tree else " (not published)."))


def publish_door(port: PlanStore, home: str | Path) -> tuple[int, str]:
    """Build a release of the work tree and put it in force with the user's one-use pass (the door live publish).

    Args:
        port: the ledger port (the pass live-publish:<sha> is taken from it).
        home: the home, the .claude folder of the harness's clone.

    Returns:
        (exit code, text): 0 published or asked, 1 refused.
    """
    sha = build(home)
    if current(home) == sha:
        return 0, f"Release {sha} is in force already."
    if not healthy(home, release_dir(home, sha)):
        return 1, f"refused: the doctor of release {sha} finds problems; run its harness/entry/doctor.py and fix them"
    if not take(port, f"live-publish:{sha}"):
        q, boot = f"{ALLOW_LABEL} publishing harness release {sha}?", anchor(home).as_posix()
        return 0, (f"Release {sha} is built and its doctor is clean. Publishing needs the user's word: ask with "
                   f"AskUserQuestion, one question, exactly: {q} Options: \"{ALLOW_LABEL}\", \"{NO_LABEL}\". Never "
                   f"fill in the answer. Then run: python3 \"{boot}\" cli live publish")
    publish(home, sha)
    return 0, f"Release {sha} is in force: hooks run it at once, MCP servers at their next call."


def update_door(port: PlanStore, home: str | Path) -> tuple[int, str]:
    """Bring the newest main into the clone and put it in force when its doctor is clean (the door live update). No
    form: the clone is exactly origin's main, which changes only by a pull request the user allowed.

    Args:
        port: the ledger port (kept for the door's shape; merged main needs no pass).
        home: the home, the .claude folder of the harness's clone.

    Returns:
        (exit code, text): 0 up to date or published; 1 refused.
    """
    pinned = pin(home)  # what runs now is the work tree: pin it before the clone changes under it
    try:
        before, after = fast_forward(home)
    except PullError as e:
        return 1, f"{pinned}refused: {e}"
    if before == after and stamp(home) == current(home):
        return 0, f"{pinned}Up to date: main {after[:12]} is the release in force."
    code, text = publish_main(home)
    news = f"main {before[:12]} -> {after[:12]}. " if before != after else ""
    return code, pinned + news + text


def publish_main(home: str | Path) -> tuple[int, str]:
    """Put the clone's main, just fast-forwarded, in force when its own doctor is clean; no form (the merge was it).

    Args:
        home: the home, the .claude folder of the harness's clone, exactly origin's main.

    Returns:
        (exit code, text): 0 in force; 1 refused (its doctor finds problems, the release in force stays).
    """
    sha = build(home)
    if current(home) == sha:
        return 0, f"Release {sha} is in force already."
    if sha in bad(home):
        return 1, (f"refused: release {sha} failed once and the fallback left it; release {current(home)} stays in "
                   f"force. Fix main with a new pull request.")
    if not healthy(home, release_dir(home, sha)):
        return 1, (f"refused: the doctor of release {sha} finds problems; release {current(home)} stays in force. "
                   f"Fix main with a new pull request.")
    publish(home, sha)
    return 0, f"Release {sha} is in force: hooks run it at once, MCP servers at their next call."


def slug(url: str) -> str:
    """The last two parts of a remote's URL or path, lower case: "owner/name" (".git" left out).

    Args:
        url: a git remote's URL or a folder path.

    Returns:
        "owner/name", or "" when the URL has fewer than two parts.
    """
    parts = [p for p in str(url).strip().replace("\\", "/").replace(":", "/").split("/") if p]
    if len(parts) < 2:
        return ""
    name = parts[-1][:-4] if parts[-1].endswith(".git") else parts[-1]
    return f"{parts[-2]}/{name}".lower()


def after_merge(home: str | Path, event: Any) -> list[str]:
    """After a merge of the harness's own repository, bring its main and put it in force (as live update does).

    Args:
        home: the home, the .claude folder of the harness's clone.
        event: the hook call; only a PostToolUse of a merge tool that merged is read.

    Returns:
        One note for the model saying which release is in force, or why the old one stays; [] for any other call.
    """
    repo = merged(event)
    if not repo:
        return []
    try:
        if slug(git(clone_root(home), "remote", "get-url", "origin")) != repo:
            return []
    except (GitError, PullError):
        return []
    try:
        before, after = fast_forward(home)
    except PullError as e:
        return [f"The harness keeps release {current(home)} after the merge: {e}"]
    _, text = publish_main(home)
    return [f"After the merge, main {before[:12]} -> {after[:12]}. {text}"]


def pin(home: str | Path) -> str:
    """Put the code that runs now in force when no release is (boot then runs the work tree); the pin text.

    Args:
        home: the home, the .claude folder of the harness's clone.

    Returns:
        "Pinned the code that runs now as release <sha>. ", or "" when a release is in force already.
    """
    if current(home) is not None:
        return ""
    sha = build(home)
    publish(home, sha)
    return f"Pinned the code that runs now as release {sha}. "


TOOLS_HINT = ("Its tools: mcp__harness__find, mcp__harness__guide and mcp__harness__run when this session has them. "
              "If it has none, the same from the shell: python3 \"{boot}\" cli tool guide <block> lists a block's "
              "actions, python3 \"{boot}\" cli tool run <block> <action> '<args as JSON>' runs one, python3 \"{boot}\" "
              "cli tool find <words> finds what fits. Read the skill work before any work: guide, name work, mode "
              "skills (from the shell: python3 \"{boot}\" cli tool guide work --mode skills).")


def tools_hint(home: str | Path) -> str:
    """How a session reaches the tools and which skill it reads first (the door live hint prints it).

    Args:
        home: the home, the .claude folder of the harness's clone.

    Returns:
        The hint, naming the home's anchor.
    """
    return TOOLS_HINT.format(boot=anchor(home).as_posix())


def release_hint(home: str | Path) -> str:
    """The hint as the release in force writes it (its door live hint); this code's own when it cannot be asked.

    Args:
        home: the home, the .claude folder of the harness's clone.

    Returns:
        The hint text.
    """
    try:
        done = subprocess.run([sys.executable, str(anchor(home)), "cli", "live", "hint"], capture_output=True,
                              timeout=30)
        text = done.stdout.decode("utf-8").strip()
        if done.returncode == 0 and text:
            return text
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return tools_hint(home)


def session_began(home: str | Path, payload: str) -> None:
    """Record that a session began: its row in the ledger, and a higher epoch when its context was compacted or
    cleared; then the ledger's upkeep. It never raises: a start is never blocked.

    Args:
        home: the home, the .claude folder.
        payload: the SessionStart hook's JSON ({session_id, source}); anything else records nothing.
    """
    try:
        data = json.loads(payload or "{}")
        sid = str(data.get("session_id") or "") if isinstance(data, dict) else ""
        if sid:
            from harness.assemble.engine.ports import LedgerPort  # the port reads this module's siblings
            port = LedgerPort(home)
            port.session_started(sid, str(data.get("source") or ""))
            port.upkeep()  # roll up, prune, back up: once a day in effect
    except Exception as e:
        sys.stderr.write(f"harness: the session start was not recorded ({type(e).__name__}: {e})\n")


def session_update(home: str | Path) -> str:
    """The text the session reads when it begins: which harness runs and why, and how to reach its tools (Claude Code
    can start before the setup script registers the MCP server, so a session may have none of them). The hint is the
    release's own when this start put a newer one in force.

    Args:
        home: the home, the .claude folder of the harness's clone.

    Returns:
        The text for the session: harness_update's words, then the tools hint.
    """
    ran = current(home) or stamp(home)
    text = harness_update(home)
    return f"{text} {tools_hint(home) if current(home) == ran else release_hint(home)}"


def harness_update(home: str | Path) -> str:
    """Bring the harness to the newest main of its clone, and put it in force when its doctor is clean.

    Args:
        home: the home, the .claude folder of the harness's clone.

    Returns:
        Which harness runs and why (kept, up to date, or brought up to date).
    """
    pinned = pin(home)
    try:
        before, after = fast_forward(home)
    except PullError as e:
        return f"{pinned}The harness keeps release {current(home)}: {e}"
    sha = build(home)
    if current(home) == sha:
        return f"{pinned}The harness is up to date: main {after[:12]}, release {sha}."
    if sha in bad(home):
        return f"{pinned}The harness keeps release {current(home)}: release {sha} of main {after[:12]} failed once."
    if not healthy(home, release_dir(home, sha)):
        return f"{pinned}The harness keeps release {current(home)}: the doctor of main {after[:12]} finds problems."
    publish(home, sha)
    return f"{pinned}The harness was brought up to date: main {before[:12]} -> {after[:12]}, release {sha} in force."
