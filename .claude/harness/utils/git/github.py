"""GitHub REST, the few calls orchestra makes (open a pull request, read it, merge it), through the gh CLI's `gh api`
(REST only; it is logged in on a PC, and the network proxy gives it its credentials in the cloud). No token is read or
written here."""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any

TIMEOUT = 60
REPO = re.compile(r"^https://(?:[^@/]+@)?github\.com/(?P<owner>[\w.-]+)/(?P<name>[\w.-]+?)(?:\.git)?/?$")


class GitHubError(RuntimeError):
    """A GitHub call failed: not a GitHub URL, gh is missing, or GitHub answered an error (the message says which)."""


def repo_of(url: str) -> str:
    """The owner/name of a GitHub repository URL.

    Args:
        url: https://github.com/<owner>/<name>(.git).

    Returns:
        "<owner>/<name>".

    Raises:
        GitHubError: the URL is not of a GitHub repository.
    """
    m = REPO.match(str(url).strip())
    if not m:
        raise GitHubError(f"{url} is not the https URL of a GitHub repository")
    return f"{m['owner']}/{m['name']}"


def words_of(method: str, path: str, fields: dict[str, Any] | None = None) -> list[str]:
    """The gh command of one call: a text field as text (-f), a bool or a number typed (-F), as GitHub wants it.

    Args:
        method: GET, POST, PUT...
        path: the endpoint, e.g. "repos/o/r/pulls", or "graphql".
        fields: the fields of the body.

    Returns:
        The words of the command.
    """
    words = ["gh", "api", "-X", method, path]
    for key, value in (fields or {}).items():
        if isinstance(value, bool):
            words += ["-F", f"{key}={'true' if value else 'false'}"]
        elif isinstance(value, int):
            words += ["-F", f"{key}={value}"]
        else:
            words += ["-f", f"{key}={value}"]
    return words


def call(method: str, path: str, fields: dict[str, Any] | None = None) -> Any:
    """One REST call (or GraphQL, path "graphql" with a query field): `gh api -X <method> <path> -f key=value...`.

    Args:
        method: GET, POST, PUT...
        path: the endpoint, e.g. "repos/o/r/pulls".
        fields: the fields of the body (words_of: text, bool, number).

    Returns:
        The decoded JSON answer ({} for an empty one).

    Raises:
        GitHubError: gh cannot start, times out, or exits non-zero (GitHub's message in it).
    """
    out = text(method, path, fields)
    try:
        return json.loads(out) if out.strip() else {}
    except ValueError as e:
        raise GitHubError(f"gh api {method} {path}: the answer is not JSON") from e


def text(method: str, path: str, fields: dict[str, Any] | None = None) -> str:
    """One call whose answer is read as text, as GitHub gives it (a job's log is plain text, not JSON).

    Args:
        method: GET, POST, PUT...
        path: the endpoint, e.g. "repos/o/r/actions/jobs/1/logs".
        fields: the fields of the body (words_of).

    Returns:
        The answer as text.

    Raises:
        GitHubError: gh cannot start, times out, or exits non-zero (GitHub's message in it).
    """
    words = words_of(method, path, fields)
    try:
        p = subprocess.run(words, capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitHubError(f"gh api {method} {path}: {e}") from e
    if p.returncode != 0:
        raise GitHubError(f"gh api {method} {path}: {(p.stderr or p.stdout).strip()[-600:]}")
    return p.stdout
