"""Protected branches from the forge (docs/system.md section 2): the repository says which of its branches are
protected (GitHub branch protection, through gh api), and the harness keeps the answer in the ledger for 10 minutes,
so a hook asks at most that often. It never protects less: the caller always adds main and master, and when the forge
cannot be reached the last list it gave stays. Only a repository whose origin is on github.com is asked."""
from __future__ import annotations

import json
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from harness.utils.git import github
from harness.utils.git.run import GitError, git
from harness.utils.plan.item_checks import repo_key
from harness.utils.shapes import PlanStore

TTL_MS = 10 * 60 * 1000
KIND = "forge.protected"
LAST = "SELECT text, at FROM pl_notes WHERE kind = ? AND target = ? ORDER BY at DESC, rowid DESC LIMIT 1"
KEEP = "INSERT INTO pl_notes (uid, kind, target, key, text, why, sid, at) VALUES (?, ?, ?, '', ?, '', '', ?)"


def slug_of(repo: str | Path) -> str:
    """The owner/name of a repository whose origin is on github.com.

    Args:
        repo: a folder of the repository.

    Returns:
        "owner/name"; "" for no repository, no origin, or an origin on another host.
    """
    if not repo or not Path(repo).is_dir():
        return ""
    try:
        origin = git(repo, "remote", "get-url", "origin").strip()
    except GitError:
        return ""
    return repo_key(origin) if "github.com" in origin.lower() else ""


def ask_github(slug: str) -> list[str]:
    """The protected branches GitHub names for a repository.

    Args:
        slug: owner/name.

    Returns:
        Their names, sorted.

    Raises:
        GitHubError: gh cannot reach GitHub or GitHub refuses.
    """
    answer = github.call("GET", f"repos/{slug}/branches?protected=true&per_page=100")
    if not isinstance(answer, list):
        return []
    return sorted({b["name"] for b in answer if isinstance(b, dict) and isinstance(b.get("name"), str)})


def protected_names(repo: str | Path, port: PlanStore, ask: Callable[[str], list[str]] = ask_github,
                    now_ms: int | None = None) -> list[str]:
    """The branches the forge protects in a repository: the list kept in the ledger when it is younger than 10
    minutes, else a new answer of the forge (kept); the last list when the forge cannot be reached.

    Args:
        repo: a folder of the repository.
        port: the ledger port (read and write).
        ask: ask(slug) -> the protected names (GitHub by default; a test gives its own).
        now_ms: the time in ms (now by default).

    Returns:
        The names; [] for a repository not on github.com, or when nothing was ever learned.
    """
    slug = slug_of(repo)
    if not slug:
        return []
    now = int(time.time() * 1000) if now_ms is None else now_ms
    try:
        row = port.read(lambda con: con.execute(LAST, (KIND, slug)).fetchone())
        last = [str(n) for n in json.loads(row[0])] if row else None
    except (ValueError, TypeError, OSError) as e:
        sys.stderr.write(f"harness: the protected branches of {slug} were not read ({type(e).__name__}: {e})\n")
        row, last = None, None
    if row and now - int(row[1]) < TTL_MS:
        return list(last or [])
    try:
        names = [str(n) for n in ask(slug)]
    except (github.GitHubError, OSError, ValueError, KeyError, TypeError):
        return list(last or [])  # the forge cannot be reached: never protect less than before
    try:
        port.write(lambda con, rec: con.execute(KEEP, (uuid.uuid4().hex, KIND, slug, json.dumps(names), now)))
    except Exception as e:  # keeping the answer never changes it
        sys.stderr.write(f"harness: the protected branches of {slug} were not kept ({type(e).__name__}: {e})\n")
    return names
