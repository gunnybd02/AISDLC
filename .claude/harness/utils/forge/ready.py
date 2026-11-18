"""The ready report (docs/system.md section 4): for each repo a plan names, what its forge says: reachable, its base
exists, issues are on, its base is protected. A report, never a gate: a forge that cannot be reached, or that is off,
is reported and the plan is still kept. Only a repository on github.com is asked."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

from harness.utils.git.github import GitHubError
from harness.utils.plan.item_checks import repo_key

Call = Callable[..., Any]  # call(method, path) -> the decoded JSON answer (utils/git/github.call)


def short(error: Exception) -> str:
    """The last line of an error, at most 80 characters.

    Args:
        error: the error.

    Returns:
        Its text, cut.
    """
    text = str(error).strip().splitlines()[-1] if str(error).strip() else type(error).__name__
    return text[:80]


def ready_line(name: str, spec: dict[str, Any], call: Optional[Call]) -> str:
    """One repo's line: what its forge says, never an error.

    Args:
        name: the repo's name in the plan.
        spec: {url, base?, ...}.
        call: call(method, path) of GitHub REST; None when the forge is off.

    Returns:
        "Ready: <name> | reachable yes | base <base> exists | issues on | <base> protected", or what could not be read.
    """
    url, base, head = str(spec.get("url") or ""), str(spec.get("base") or "main"), f"Ready: {name}"
    if "github.com" not in url.lower():
        return f"{head} | not on GitHub: not checked"
    if call is None:
        return f"{head} | not checked (the forge is off)"
    slug = repo_key(url)
    try:
        info = call("GET", f"repos/{slug}")
    except (GitHubError, OSError, ValueError) as e:
        return f"{head} | not reachable ({short(e)})"
    issues = "issues on" if isinstance(info, dict) and info.get("has_issues") else "issues off"
    try:
        branch = call("GET", f"repos/{slug}/branches/{base}")
    except (GitHubError, OSError, ValueError):
        return f"{head} | reachable yes | base {base} missing | {issues}"
    guarded = "protected" if isinstance(branch, dict) and branch.get("protected") else "not protected"
    return f"{head} | reachable yes | base {base} exists | {issues} | {base} {guarded}"


def report(repos: Any, call: Optional[Call]) -> list[str]:
    """The ready line of each repo of a plan.

    Args:
        repos: the plan's repos item ({name: spec}); anything else has none.
        call: call(method, path) of GitHub REST; None when the forge is off.

    Returns:
        One line per repo, in the plan's order.
    """
    if not isinstance(repos, dict):
        return []
    return [ready_line(name, spec, call) for name, spec in repos.items() if isinstance(spec, dict)]
