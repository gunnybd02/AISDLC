"""Fetch: a child's branch as the parent sees it (docs/05b-orchestra-cloud.md part 3): a temporary checkout of the unit's
repository, a run of the unit's test command in it, with the harness's own variables left out, and the parent's own
commits (the empty start commit of a child's branch), pushed with a plain branch push."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from harness.utils.git.run import GitError, git
from harness.utils.plan.verify import project_env

TAIL = 1500


class FetchError(ValueError):
    """A branch cannot be fetched or checked out; the message says why."""


def same_repo(unit: dict[str, Any], repo: str) -> bool:
    """Whether a unit lives in the parent's own repository (no repo named, or the same as its origin).

    Args:
        unit: the unit's spec.
        repo: the parent's repository root.

    Returns:
        True when the parent's clone holds the unit.
    """
    if not unit.get("repo"):
        return True
    try:
        origin = git(repo, "config", "--get", "remote.origin.url").strip()
    except GitError:
        return False
    norm = lambda u: re.sub(r"(?<=//)[^/@]*@", "", u).rstrip("/").removesuffix(".git").lower()  # noqa: E731
    return norm(origin) == norm(unit["repo"])


@contextmanager
def checkout(unit: dict[str, Any], repo: str, ref: str) -> Iterator[str]:
    """A temporary checkout of a branch of the unit's repository, removed afterwards: a detached worktree of the
    parent's clone when the unit lives there, else a shallow clone of the unit's repository.

    Args:
        unit: the unit's spec.
        repo: the parent's repository root.
        ref: the branch to check out.

    Yields:
        The checkout's root.

    Raises:
        FetchError: the branch cannot be fetched or checked out.
    """
    folder = tempfile.mkdtemp(prefix="harness-check-")
    mine = same_repo(unit, repo)
    try:
        if mine:
            git(repo, "fetch", "-q", "origin", ref, timeout=300)
            git(repo, "worktree", "add", "-q", "--detach", folder, "FETCH_HEAD")
        else:
            git(folder, "clone", "-q", "--depth", "50", "--branch", ref, unit["repo"], ".", timeout=600)
        yield folder
    except GitError as e:
        raise FetchError(f"the branch {ref} cannot be checked out: {e}") from e
    finally:
        if mine:
            try:
                git(repo, "worktree", "remove", "--force", folder)
            except GitError:
                pass
        shutil.rmtree(folder, ignore_errors=True)


def rerun(folder: str, command: list[str], tests: list[str], timeout: int) -> tuple[bool, str]:
    """Run the unit's test command in its folder of the checkout: once per test file when the command names {test},
    else once.

    Args:
        folder: the unit's folder in the checkout.
        command: the unit's test command ("{python}" already this Python).
        tests: the test files of the criteria.
        timeout: the seconds each run may take.

    Returns:
        (all green, the tail of the output).
    """
    runs = [[w.replace("{test}", t) for w in command] for t in tests] if any("{test}" in w for w in command) \
        else [command]
    out, ok = [], True
    for words in runs:
        try:
            p = subprocess.run(words, cwd=folder, capture_output=True, text=True, timeout=timeout,
                               env=project_env(), stdin=subprocess.DEVNULL)
            ok, text = ok and p.returncode == 0, (p.stdout + p.stderr)
        except (OSError, subprocess.TimeoutExpired) as e:
            ok, text = False, str(e)
        out.append(f"$ {' '.join(words)}\n{text.strip()[-TAIL:]}")
    return ok, "\n".join(out)


def committer(folder: str) -> list[str]:
    """The git options that name a committer when the checkout has none: the parent's own commits on a child's branch.

    Args:
        folder: the checkout.

    Returns:
        [] when user.email is set there; else -c options naming the harness.
    """
    return [] if git_or_empty(folder, "config", "user.email") else \
        ["-c", "user.name=harness", "-c", "user.email=harness@localhost"]


def git_or_empty(folder: str, *args: str) -> str:
    """The output of a git command, or "" when it fails (an unset config value).

    Args:
        folder: the folder git runs in.
        *args: the words after git.

    Returns:
        Its output, stripped, or "".
    """
    try:
        return git(folder, *args).strip()
    except GitError:
        return ""


def put_files(unit: dict[str, Any], repo: str, ref: str, files: dict[str, str], message: str, target: str = "") -> str:
    """Commit files on a branch and push the result to a branch: a plain branch push. Files that are already there as
    given make no commit; no files at all make an empty commit (a start or a signal: the talk is in comments, never in
    files of the branch, utils/orchestra/talk.py).

    Args:
        unit: the unit's spec {repo, path, verify, base}.
        repo: the parent's repository root.
        ref: the branch the commit starts from.
        files: {path in the repository: text}; {} for an empty commit.
        message: the commit message.
        target: the branch pushed to; ref when "".

    Returns:
        The commit the target branch holds now.

    Raises:
        FetchError: the branch cannot be checked out, or the commit or the push fails.
    """
    to = target or ref
    try:
        with checkout(unit, repo, ref) as folder:
            for rel, text in files.items():
                path = Path(folder) / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                git(folder, "add", "--", rel)
            if not files:
                git(folder, *committer(folder), "commit", "-q", "--allow-empty", "-m", message)
            elif git_or_empty(folder, "diff", "--cached", "--name-only"):
                git(folder, *committer(folder), "commit", "-q", "-m", message)
            sha = git(folder, "rev-parse", "HEAD").strip()
            git(folder, "push", "-q", "origin", f"HEAD:refs/heads/{to}", timeout=300)
    except GitError as e:
        raise FetchError(f"the files were not pushed on {to}: {str(e)[-300:]}") from e
    return sha
