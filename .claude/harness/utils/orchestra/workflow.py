"""Workflow: the GitHub Actions file the parent locks on a plan branch with the acceptance tests (docs/system.md
section 6), one per repository of the plan: WORKFLOW. GitHub runs it on each push to a pull request of a child
(orch/p<plan>/<name>) into the plan branch (plan/p<plan>). It gets the harness at one pinned commit (the harness's
repository is public: no secret), runs harness ci (utils/orchestra/ci.py) with the job's read-only token, then the
test command of the child's unit in its folder ({python} is the job's Python; {test}: once per locked test). The
rules come from the pinned harness, never from the child's branch; the file is locked like the tests, so a child
that changes it is refused (its scope, harness ci, and the parent's check)."""
from __future__ import annotations

import re
import shlex
from typing import Any

from harness.utils.shapes import Card

WORKFLOW = ".github/workflows/harness-ci.yml"
CHECKOUT, SETUP, PYTHON = "actions/checkout@v4", "actions/setup-python@v5", "3.13"
SHA = re.compile(r"^[0-9a-f]{40}$")
URL = re.compile(r"^https://[A-Za-z0-9.-]+/[\w.-]+/[\w.-]+?(?:\.git)?$")


class WorkflowError(ValueError):
    """The workflow cannot be written: the harness's source is not a public https URL and a full commit sha."""


def commands(card: Card, spec: dict[str, Any]) -> list[str]:
    """The shell lines that run a child's tests in CI: its unit's test command, {python} as the job's Python, and a
    command with {test} once per locked test of the card (else per test of the card).

    Args:
        card: the child's card.
        spec: its unit's spec {repo, path, verify, base} (card.unit_spec).

    Returns:
        The lines, each quoted for the shell; [] when the unit names no test command.
    """
    words = ["python" if w == "{python}" else str(w) for w in spec.get("verify") or []]
    if not words:
        return []
    if "{test}" not in words:
        return [shlex.join(words)]
    tests = list(card.get("acTests") or []) or list(card.get("tests") or [])
    return [shlex.join([t if w == "{test}" else w for w in words]) for t in tests]


def text(plan: int, children: list[tuple[Card, dict[str, Any]]], source: dict[str, str]) -> str:
    """The workflow of one repository of a plan.

    Args:
        plan: the plan's number.
        children: (card, unit spec) of each child whose unit is in this repository.
        source: the harness to run, {url: its public https URL, sha: the full commit} (cli_live.source).

    Returns:
        The YAML text.

    Raises:
        WorkflowError: the source is no https URL without credentials, or no full commit sha.
    """
    url, sha = str(source.get("url") or ""), str(source.get("sha") or "")
    if not URL.match(url) or not SHA.match(sha):
        raise WorkflowError(f"the harness to pin is not a public https URL and a full commit ({url!r}, {sha!r})")
    base, prefix = f"plan/p{plan}", f"orch/p{plan}/"
    lines = [f"# Written by the harness for plan {plan}: harness ci on each push to a pull request of a child into "
             f"{base}.", "# Locked with the acceptance tests: never edit it by hand; a child that changes it is refused.",
             f"name: harness ci p{plan}", "'on':", "  pull_request:", f"    branches: ['{base}']",
             "permissions:", "  contents: read", "  issues: read", "  pull-requests: read",
             "jobs:", "  harness-ci:", f"    if: startsWith(github.head_ref, '{prefix}')", "    runs-on: ubuntu-latest",
             "    steps:", f"      - uses: {CHECKOUT}", "        with:", "          fetch-depth: 0",
             f"      - uses: {SETUP}", "        with:", f"          python-version: '{PYTHON}'",
             f"      - name: Get the harness at {sha[:12]}", "        run: |",
             f"          git clone --quiet {url} \"$RUNNER_TEMP/harness\"",
             f"          git -C \"$RUNNER_TEMP/harness\" checkout --quiet {sha}",
             "      - name: harness ci", "        env:", "          GH_TOKEN: ${{ github.token }}", "        run: |",
             "          python \"$RUNNER_TEMP/harness/.claude/harness/entry/cli.py\" ci --base \"$GITHUB_BASE_REF\" "
             "--head \"$GITHUB_HEAD_REF\""]
    for card, spec in children:
        runs, folder = commands(card, spec), str(spec.get("path") or ".").strip("/") or "."
        for n, line in enumerate(runs, 1):
            lines += [f"      - name: tests of {card['name']}" + (f" ({n})" if len(runs) > 1 else ""),
                      f"        if: ${{{{ !cancelled() && github.head_ref == '{prefix}{card['name']}' }}}}"]
            lines += [f"        working-directory: {folder}"] if folder != "." else []
            lines += ["        run: |", f"          {line}"]
    return "\n".join(lines) + "\n"
