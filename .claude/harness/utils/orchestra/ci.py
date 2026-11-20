"""CI: harness ci (python3 anchor.py cli ci --base <branch> --head <branch>), the child's gate run again on the forge
(docs/system.md section 7), on a machine the child cannot reach. It reads only the repository and the child's issue:
no session, no ledger, and no file of the branch for its facts. The parent's start commit ("#<issue> <name>: start",
utils/orchestra/draft.py) names the issue; the issue's machine block (utils/orchestra/issues.py) names the rest, and
the child's registration is a comment on that issue (utils/orchestra/register.registration_of). Each rule of RULES
passes or fails with why; a rule that cannot run fails as "not checked", so a red run always says what it did not see:

- branch: the head is the branch of the issue and of the registration (orch/p<plan>/<name>)
- base: the base is the plan branch the issue names (start), when it names one
- issue: the start commit names the issue, it is in the issues' format, and its block is the one the registration names
- registered: the child's registration comment is on the issue, for this child and the issue's plan
- subjects: every commit's subject starts "#<issue> <name>: " (utils/orchestra/brief.subject)
- marks: no commit message holds an AI mark (utils/git/marks.py)
- secrets: no line the branch adds holds a secret (the shapes of utils/ledger/mask.py, as gear/detect/secret.py)
- scope: every changed file is in the issue's scope (its change and tests, in the unit's folder); the talk is in
  comments, so a .harness file is outside it
- locked: no locked acceptance test changes

A branch none of whose commits changes a file (the start, and the child's empty signal commits) is WAITING."""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from harness.utils.git.github import GitHubError, repo_of
from harness.utils.git.marks import marks_in
from harness.utils.git.run import GitError, git
from harness.utils.git.staged_diff import added_between
from harness.utils.ledger.mask import SECRETS
from harness.utils.orchestra.brief import subject
from harness.utils.orchestra.issues import format_problems, read_block
from harness.utils.orchestra.locked import in_unit
from harness.utils.orchestra.register import registration_of
from harness.utils.plan.files import matches

RULES = ("branch", "base", "issue", "registered", "subjects", "marks", "secrets", "scope", "locked")
HEAD = re.compile(r"^orch/p(?P<plan>\d+)/(?P<name>[a-z0-9][a-z0-9-]{0,39})$")
START = re.compile(r"^#(?P<number>\d+) (?P<name>[a-z0-9][a-z0-9-]{0,39}): start\b")
WAITING = "no commit of the child changes a file yet"
Result = tuple[str, bool, str]


def ref_of(repo: str, branch: str) -> str:
    """The ref git reads for a branch: origin's copy when the clone has one (a CI checkout), else the local branch.

    Args:
        repo: the clone.
        branch: the branch's name.

    Returns:
        "origin/<branch>" or the branch.
    """
    try:
        git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}")
        return f"origin/{branch}"
    except GitError:
        return branch


def commits(repo: str, base: str, head: str) -> list[dict[str, Any]]:
    """The commits of head over base, oldest first, each with its message and the files it changes (against its
    first parent; [] for an empty commit).

    Args:
        repo: the clone.
        base: the base's ref.
        head: the head's ref.

    Returns:
        [{sha, message, files}].
    """
    out = []
    for sha in git(repo, "rev-list", "--reverse", "--topo-order", f"{base}..{head}").split():
        out.append({"sha": sha, "message": git(repo, "log", "-1", "--format=%B", sha).strip(),
                    "files": git(repo, "diff", "--name-only", "--no-renames", f"{sha}^1", sha).split()})
    return out


def started(log: list[dict[str, Any]], name: str) -> int:
    """The issue the parent's start commit names: the first commit of the log whose subject is "#<n> <name>: start"
    and that changes no file.

    Args:
        log: the commits over the base (commits).
        name: the child's name.

    Returns:
        The issue's number; 0 when no such commit is there.
    """
    for c in log:
        found = START.match(c["message"])
        if found and found["name"] == name and not c["files"]:
            return int(found["number"])
    return 0


def slug_of(repo: str, slug: str = "") -> str:
    """The repository's owner/name on GitHub: the one given, else the one of its origin's URL.

    Args:
        repo: the clone.
        slug: owner/name when the caller knows it (GITHUB_REPOSITORY in Actions).

    Returns:
        owner/name; "" when it cannot be told.
    """
    if slug:
        return slug
    try:
        return repo_of(git(repo, "config", "--get", "remote.origin.url").strip())
    except (GitError, GitHubError):
        return ""


def check(repo: str, base: str, head: str, github: Callable[..., Any], sha: str = "", slug: str = "") -> list[Result]:
    """Run every rule of RULES on the branch head over base.

    Args:
        repo: a clone that holds both branches (origin's copies are read first).
        base: the base branch's name (the pull request's base).
        head: the child's branch's name (the pull request's head).
        github: call(method, path, fields?) -> the JSON answer (utils/git/github.call).
        sha: the commit under test (the pull request's head of this run); "" for the branch's tip on origin. Live run
            5: a job read the tip after a later push, not the commit it tested.
        slug: the repository's owner/name; "" for the one of its origin (slug_of).

    Returns:
        One (rule, passed, why) per rule, in the order of RULES.
    """
    found = HEAD.match(head)
    if not found:
        return fill([("branch", False, f"{head} is no branch of a child (orch/p<plan>/<name>)")],
                    "the head is no branch of a child")
    name, tip = found["name"], sha or ref_of(repo, head)
    try:
        log = commits(repo, ref_of(repo, base), tip)
    except GitError as e:
        return fill([], f"git cannot read {head} over {base}: {str(e)[-200:]}")
    if not any(c["files"] for c in log):  # the start and empty signals alone: the child has no work yet
        return [(rule, True, WAITING) for rule in RULES]
    number, slug = started(log, name), slug_of(repo, slug)
    if not number:
        return fill([("issue", False, f"no start commit '#<issue> {name}: start' over {base} names the issue")],
                    "no start commit names the issue")
    if not slug:
        return fill([("issue", False, "not checked: the repository on GitHub is not known (--repo)")],
                    "the repository on GitHub is not known")
    out: list[Result] = []
    registration, why = registered(slug, number, name, github)
    block = issue_rule(slug, number, registration, github, out)
    out.append(branch_rule(head, number, block, registration))
    out.append(base_rule(base, block))
    if not why and block and registration.get("planSha") != block.get("planSha"):
        why = "the registration is for another plan"
    out.append(("registered", not why, why or f"comment {registration.get('id')} on issue #{number} registers {name} "
                "for its plan"))
    start = block.get("start") or base  # the plan branch the child's branch starts from
    if start != base:
        try:
            log = commits(repo, ref_of(repo, start), tip)
        except GitError as e:
            return fill(out, f"git cannot read {head} over {start}: {str(e)[-200:]}")
    prefix = subject(number, name, "")
    wrong = [c["sha"][:12] for c in log if not c["message"].startswith(prefix)]
    out.append(("subjects", not wrong, f"every commit starts {prefix!r}" if not wrong else
                f"these commits do not start {prefix!r}: {', '.join(wrong)}"))
    marked = [f"{c['sha'][:12]} ({', '.join(marks_in(c['message']))})" for c in log if marks_in(c["message"])]
    out.append(("marks", not marked, "no AI mark" if not marked else f"AI marks in {'; '.join(marked)}"))
    out += files_rules(repo, ref_of(repo, start), tip, block)
    order = {rule: n for n, rule in enumerate(RULES)}
    return sorted(out, key=lambda r: order[r[0]])


def registered(slug: str, number: int, name: str, github: Callable[..., Any]) -> tuple[dict[str, Any], str]:
    """The child's registration comment on its issue.

    Args:
        slug: the repository's owner/name.
        number: the issue's number.
        name: the child's name.
        github: the GitHub call.

    Returns:
        (its meta, or {}; why the registered rule fails, or "").
    """
    try:
        comments = github("GET", f"repos/{slug}/issues/{number}/comments?per_page=100") or []
    except GitHubError as e:
        return {}, f"not checked: the comments of issue #{number} cannot be read: {str(e)[-160:]}"
    found = registration_of(comments if isinstance(comments, list) else [], name)
    return found, "" if found else f"issue #{number} holds no registration comment of {name}"


def branch_rule(head: str, number: int, block: dict[str, Any], registration: dict[str, Any]) -> Result:
    """The branch rule: the head is the branch the issue and the registration name.

    Args:
        head: the child's branch's name.
        number: the issue's number.
        block: the issue's block; {} when the issue was not read.
        registration: the registration's meta; {} when there is none.

    Returns:
        The result.
    """
    if not block and not registration:
        return "branch", False, "not checked: neither the issue nor a registration was read"
    named = {block.get("branch") if block else head, registration.get("branch") if registration else head}
    if named == {head}:
        return "branch", True, f"{head} is the branch of issue #{number}"
    return ("branch", False, f"{head}, but the issue says {block.get('branch')} and the registration "
            f"{registration.get('branch')}")


def base_rule(base: str, block: dict[str, Any]) -> Result:
    """The base rule: the pull request goes into the plan branch the issue names.

    Args:
        base: the base branch's name.
        block: the issue's block; {} when the issue was not read.

    Returns:
        The result.
    """
    start = block.get("start")
    if not block:
        return "base", False, "not checked: the issue was not read"
    if not start:
        return "base", True, "the issue names no plan branch"
    return "base", start == base, f"{base} is {'' if start == base else 'not '}the plan branch {start}"


def issue_rule(slug: str, number: int, registration: dict[str, Any], github: Callable[..., Any],
               out: list[Result]) -> dict[str, Any]:
    """Read the issue the start commit names and add the issue rule to out.

    Args:
        slug: the repository's owner/name.
        number: the issue's number.
        registration: the registration's meta; {} when there is none (then only the format is checked).
        github: the GitHub call.
        out: the results so far.

    Returns:
        The issue's block; {} when it cannot be read or is not in format, or not the registered one.
    """
    name = f"issue #{number}"
    try:
        body = str((github("GET", f"repos/{slug}/issues/{number}") or {}).get("body") or "")
    except GitHubError as e:
        out.append(("issue", False, f"{name} cannot be read: {str(e)[-160:]}"))
        return {}
    problems = format_problems(body)
    block, sha = read_block(body)
    if block and registration and sha != registration.get("issueSha"):
        problems.append("its block is not the one the registration names")
    out.append(("issue", not problems, f"{name} is in format" + (" and registered" if registration else "")
                if not problems else f"{name}: " + "; ".join(problems)))
    return {} if problems else block


def files_rules(repo: str, base: str, head: str, block: dict[str, Any]) -> list[Result]:
    """The secrets, scope and locked rules on the files the branch changes.

    Args:
        repo: the clone.
        base: the base's ref.
        head: the head's ref.
        block: the issue's block; {} when the issue was not read.

    Returns:
        The three results.
    """
    added = added_between(repo, base, head)
    kinds = [f"{path} holds {kind}" for path, lines in sorted(added.items()) for kind, pattern in SECRETS.items()
             if any(pattern.search(line) for line in lines)]
    out = [("secrets", not kinds, "no secret in an added line" if not kinds else "; ".join(kinds))]
    if not block:
        return out + [(rule, False, "not checked: the issue was not read") for rule in ("scope", "locked")]
    changed = git(repo, "diff", "--name-only", "--no-renames", f"{base}...{head}").split()
    unit = {"path": block.get("path") or "."}
    allowed = [in_unit(unit, p) for p in list(block.get("scope") or []) + list(block.get("tests") or [])]
    outside = [f for f in changed if not matches(allowed, f)]
    locked = [f for f in changed if f in {in_unit(unit, t) for t in block.get("acTests") or []}]
    return out + [("scope", not outside, "every changed file is in the scope of the issue" if not outside else
                   f"outside the scope of the issue: {', '.join(outside)}"),
                  ("locked", not locked, "no locked acceptance test changes" if not locked else
                   f"locked acceptance tests changed: {', '.join(locked)}")]


def fill(done: list[Result], why: str) -> list[Result]:
    """The results of a run that stopped early: each rule not run fails as not checked.

    Args:
        done: the results so far.
        why: why the other rules were not run.

    Returns:
        One result per rule, in the order of RULES.
    """
    seen = {r[0]: r for r in done}
    return [seen.get(rule, (rule, False, f"not checked: {why}")) for rule in RULES]


def has_code(repo: str, base: str, head: str, sha: str = "") -> bool:
    """Whether the child's branch holds work of its own over base: a commit that changes a file (the start commit and
    the child's signal commits change none). Until then the workflow skips the child's tests, which are red before any
    code (live run 2: the draft was red when it opened); harness ci itself runs every rule each time.

    Args:
        repo: the clone.
        base: the base branch's name.
        head: the child's branch's name.
        sha: the commit under test; "" for the branch's tip on origin.

    Returns:
        True when such a commit is on the branch, or when that cannot be told (the tests then run).
    """
    if not HEAD.match(head):
        return True
    try:
        log = commits(repo, ref_of(repo, base), sha or ref_of(repo, head))
    except GitError:
        return True
    return any(c["files"] for c in log)


def report(repo: str, base: str, head: str, github: Callable[..., Any], sha: str = "",
           slug: str = "") -> tuple[bool, str]:
    """Run the rules and write the text harness ci prints.

    Args:
        repo: the clone.
        base: the base branch's name.
        head: the child's branch's name.
        github: the GitHub call.
        sha: the commit under test; "" for the branch's tip on origin.
        slug: the repository's owner/name; "" for the one of its origin.

    Returns:
        (all passed, the text: a head line, one line per rule, the result).
    """
    results = check(repo, base, head, github, sha, slug)
    failed = [rule for rule, ok, _ in results if not ok]
    if all(why == WAITING for _, _, why in results):
        return True, "\n".join([f"harness ci: {head} into {base}", f"WAIT: {WAITING}.",
                                "Result: WAITING, nothing to check yet."])
    lines = [f"harness ci: {head} into {base}"] + [f"{'PASS' if ok else 'FAIL'} {rule}: {why}"
                                                    for rule, ok, why in results]
    lines.append("Result: GREEN, every rule passed." if not failed else
                 f"Result: RED, {len(failed)} rule(s) failed: {', '.join(failed)}.")
    return not failed, "\n".join(lines)
