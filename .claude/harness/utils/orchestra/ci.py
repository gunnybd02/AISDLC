"""CI: harness ci (python3 anchor.py cli ci --base <branch> --head <branch>), the child's gate run again on the forge
(docs/system.md section 7), on a machine the child cannot reach. It reads only the repository and the child's issue:
no session, no ledger. The registration record (utils/orchestra/register.py, RECORD) names the issue; the issue's
machine block (utils/orchestra/issues.py) names the rest. Each rule of RULES passes or fails with why; a rule that
cannot run fails as "not checked", so a red run always says what it did not see:

- branch: the head is the branch of the registration and of the issue (orch/p<plan>/<name>)
- base: the base is the plan branch the issue names (start), when it names one
- issue: the issue is in the issues' format and its block is the one the registration names (its sha256)
- registered: the first commit over the base adds the registration alone, for this child and the issue's plan
- subjects: every commit's subject starts "#<issue> <name>: " (utils/orchestra/brief.subject)
- marks: no commit message holds an AI mark (utils/git/marks.py)
- secrets: no line the branch adds holds a secret (the shapes of utils/ledger/mask.py, as gear/detect/secret.py)
- scope: every changed file is in the issue's scope (its change and tests, in the unit's folder) or the child's own
  .harness files (its registration, notes and receipt)
- locked: no locked acceptance test changes"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from harness.utils.git.github import GitHubError
from harness.utils.git.marks import marks_in
from harness.utils.git.run import GitError, git
from harness.utils.git.staged_diff import added_between
from harness.utils.ledger.mask import SECRETS
from harness.utils.orchestra.brief import NOTES, subject
from harness.utils.orchestra.draft import START
from harness.utils.orchestra.issues import format_problems, read_block
from harness.utils.orchestra.locked import in_unit
from harness.utils.orchestra.register import RECORD, RECORD_FORMAT
from harness.utils.orchestra.work import RECEIPTS
from harness.utils.plan.files import matches

RULES = ("branch", "base", "issue", "registered", "subjects", "marks", "secrets", "scope", "locked")
HEAD = re.compile(r"^orch/p(?P<plan>\d+)/(?P<name>[a-z0-9][a-z0-9-]{0,39})$")
WAITING = "only the parent's start commit is on the branch; the child has not registered yet"
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
    first parent).

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


def record_of(repo: str, first: dict[str, Any], name: str) -> dict[str, Any]:
    """The registration a commit holds, when the files it changes are the registration alone.

    Args:
        repo: the clone.
        first: a commit ({sha: any ref, files: what it changes}); the tip with files [the record] reads the record
            the branch holds now.
        name: the child's name.

    Returns:
        The record; {} when there is none, or other files change with it.
    """
    rel = RECORD.format(name=name)
    if first.get("files") != [rel]:
        return {}
    try:
        record = json.loads(git(repo, "show", f"{first['sha']}:{rel}"))
    except (GitError, ValueError):
        return {}
    return record if isinstance(record, dict) and record.get("format") == RECORD_FORMAT else {}


def check(repo: str, base: str, head: str, github: Callable[..., Any], sha: str = "") -> list[Result]:
    """Run every rule of RULES on the branch head over base.

    Args:
        repo: a clone that holds both branches (origin's copies are read first).
        base: the base branch's name (the pull request's base).
        head: the child's branch's name (the pull request's head).
        github: call(method, path, fields?) -> the JSON answer (utils/git/github.call).
        sha: the commit under test (the pull request's head of this run); "" for the branch's tip on origin. Live run
            5: a job read the tip after a later push, not the commit it tested.

    Returns:
        One (rule, passed, why) per rule, in the order of RULES.
    """
    found = HEAD.match(head)
    if not found:
        return fill([("branch", False, f"{head} is no branch of a child (orch/p<plan>/<name>)")],
                    "the head is no branch of a child")
    name, rel, opened = found["name"], RECORD.format(name=found["name"]), START.format(name=found["name"])
    tip = sha or ref_of(repo, head)
    record = record_of(repo, {"sha": tip, "files": [rel]}, name)  # the record at the commit under test
    if not record:
        try:
            only_start = [c["files"] for c in commits(repo, ref_of(repo, base), tip)] == [[opened]]
        except GitError:
            only_start = False
        if only_start:  # the parent's start commit alone: the draft pull request is open, the child not yet
            return [(rule, True, WAITING) for rule in RULES]
        return fill([("registered", False, f"{head} holds no registration ({rel})")], "no registration names the issue")
    out: list[Result] = []
    block = issue_rule(record, github, out)
    planned = record.get("branch") == head and (not block or block.get("branch") == head)
    out.append(("branch", planned, f"{head} is the branch of issue #{record.get('issue')}" if planned else
                f"{head}, but the registration says {record.get('branch')} and the issue {block.get('branch')}"))
    out.append(base_rule(base, block))
    start = block.get("start") or base  # the plan branch the child's branch starts from
    try:
        log = commits(repo, ref_of(repo, start), tip)
    except GitError as e:
        return fill(out, f"git cannot read {head} over {start}: {str(e)[-200:]}")
    body = log[1:] if log and log[0]["files"] == [opened] else log  # after the parent's start commit
    first = body[0] if body else {"sha": "", "files": []}
    why = ""
    if record_of(repo, first, name) != record:
        why = (f"{head} does not start with its registration: its first commit over {start} changes "
               f"{', '.join(first['files']) or 'nothing'}")
    elif record.get("child") != name or (block and record.get("planSha") != block.get("planSha")):
        why = "the registration is for another child or plan"
    out.append(("registered", not why, why or f"the first commit {first['sha'][:12]} over {start} registers {name} "
                f"for issue #{record.get('issue')}"))
    prefix = subject(record.get("issue"), name, "")
    wrong = [c["sha"][:12] for c in log if not c["message"].startswith(prefix)]
    out.append(("subjects", not wrong, f"every commit starts {prefix!r}" if not wrong else
                f"these commits do not start {prefix!r}: {', '.join(wrong)}"))
    marked = [f"{c['sha'][:12]} ({', '.join(marks_in(c['message']))})" for c in log if marks_in(c["message"])]
    out.append(("marks", not marked, "no AI mark" if not marked else f"AI marks in {'; '.join(marked)}"))
    out += files_rules(repo, ref_of(repo, start), tip, name, block)
    order = {rule: n for n, rule in enumerate(RULES)}
    return sorted(out, key=lambda r: order[r[0]])


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


def issue_rule(record: dict[str, Any], github: Callable[..., Any], out: list[Result]) -> dict[str, Any]:
    """Read the issue the registration names and add the issue rule to out.

    Args:
        record: the registration.
        github: the GitHub call.
        out: the results so far.

    Returns:
        The issue's block; {} when it cannot be read or is not the registered one.
    """
    name = f"issue #{record.get('issue')}"
    try:
        body = str((github("GET", f"repos/{record.get('repo')}/issues/{record.get('issue')}") or {}).get("body") or "")
    except GitHubError as e:
        out.append(("issue", False, f"{name} cannot be read: {str(e)[-160:]}"))
        return {}
    problems = format_problems(body)
    block, sha = read_block(body)
    if block and sha != record.get("issueSha"):
        problems.append("its block is not the one the registration names")
    out.append(("issue", not problems, f"{name} is in format and registered" if not problems else
                f"{name}: " + "; ".join(problems)))
    return {} if problems else block


def files_rules(repo: str, base: str, head: str, name: str, block: dict[str, Any]) -> list[Result]:
    """The secrets, scope and locked rules on the files the branch changes.

    Args:
        repo: the clone.
        base: the base's ref.
        head: the head's ref.
        name: the child's name.
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
    own = [RECORD.format(name=name), f"{NOTES}/{name}/", f"{RECEIPTS}/{name}.json"]
    outside = [f for f in changed if not matches(allowed + own, f)]
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
    """Whether the child's branch holds work of its own over base: a commit that is neither the parent's start commit
    nor the registration alone. Until then the workflow skips the child's tests, which are red before any code (live
    run 2: the draft was red when it opened); harness ci itself runs every rule each time.

    Args:
        repo: the clone.
        base: the base branch's name.
        head: the child's branch's name.
        sha: the commit under test; "" for the branch's tip on origin.

    Returns:
        True when such a commit is on the branch, or when that cannot be told (the tests then run).
    """
    found = HEAD.match(head)
    if not found:
        return True
    alone = ([START.format(name=found["name"])], [RECORD.format(name=found["name"])])
    try:
        log = commits(repo, ref_of(repo, base), sha or ref_of(repo, head))
    except GitError:
        return True
    return any(c["files"] not in alone for c in log)


def report(repo: str, base: str, head: str, github: Callable[..., Any], sha: str = "") -> tuple[bool, str]:
    """Run the rules and write the text harness ci prints.

    Args:
        repo: the clone.
        base: the base branch's name.
        head: the child's branch's name.
        github: the GitHub call.
        sha: the commit under test; "" for the branch's tip on origin.

    Returns:
        (all passed, the text: a head line, one line per rule, the result).
    """
    results = check(repo, base, head, github, sha)
    failed = [rule for rule, ok, _ in results if not ok]
    if all(why == WAITING for _, _, why in results):
        return True, "\n".join([f"harness ci: {head} into {base}", f"WAIT: {WAITING}.",
                                "Result: WAITING, nothing to check yet."])
    lines = [f"harness ci: {head} into {base}"] + [f"{'PASS' if ok else 'FAIL'} {rule}: {why}"
                                                    for rule, ok, why in results]
    lines.append("Result: GREEN, every rule passed." if not failed else
                 f"Result: RED, {len(failed)} rule(s) failed: {', '.join(failed)}.")
    return not failed, "\n".join(lines)
