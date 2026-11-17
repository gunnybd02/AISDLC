"""AgentPlaces: what agent files never take, as rule actions (kind agent, what: the rule's place); the when rows
of gear/rules decide them.
- commit.agent_files: a commit of a unit (any repository but the home, which holds the harness) holds agent files
  (.claude/, CLAUDE.md, CLAUDE.local.md, .mcp.json, AGENTS.md);
- agent.rules: a write into a .claude/rules/ folder (a rule is a skill: harness/mcp/skill_docs/);
- agent.memory: a write into a memory/ folder of .claude (a point to keep is a note, kept in SQL);
- agent.registry: a write to the behaviour registry file (.claude/project/behaviors.json: add test, behaviors add);
- agent.anchor: a write to what decides which code a session runs: anchor.py beside a .claude that holds a harness,
  .claude/entry/boot.py (the forwarder of the old path), .claude/settings.json, or the .mcp.json beside .claude (the
  user changes them outside a session);
- agent.session_start: a shell line that runs the SessionStart entry, which puts the newest main in force without the
  user's word: only Claude Code runs it, when a session begins (in a session: live update and the form)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from harness.gear.translate.git_rules import agent_file
from harness.utils.contracts import RULE_ACTIONS, Event, Translator
from harness.utils.shapes import Facts


def beside_harness(path: str | Path) -> bool:
    """Whether the file sits beside a .claude folder that holds a harness: the root of a core repository.

    Args:
        path: the file written (absolute).

    Returns:
        True when <its folder>/.claude/harness is a folder.
    """
    return os.path.isdir(os.path.join(os.path.dirname(str(path)), ".claude", "harness"))


def parts(path: str | Path) -> list[str]:
    """The parts of a path, lower case, either slash, empty parts left out.

    Args:
        path: a file path.

    Returns:
        Its parts in order, e.g. ["c:", "repo", ".claude", "rules", "x.md"].
    """
    return [p.lower() for p in str(path).replace("\\", "/").split("/") if p]


class AgentPlaces(Translator):
    """The rule actions of agent files: what is one of session_start, unit_commit, rules, memory, registry, anchor."""
    READS = ("harness_session_start", "commit_repo", "commit_files", "git_view", "writes")
    VOCABULARY = ("kind", "what")

    def translate(self, event: Event, facts: Optional[Facts] = None) -> Facts:
        """One rule action (kind agent) for a shell line that runs the SessionStart entry, a unit's commit that holds
        agent files, and each write to a rules, memory, registry or anchor place; {} when there is none."""
        facts = facts or {}
        out: list[dict[str, Any]] = []

        def add(what: str, detail: str) -> None:
            out.append({"kind": "agent", "what": what, "detail": detail})
        if event.kind == "PreToolUse" and facts.get("harness_session_start"):
            add("session_start", event.input.get("command", ""))
        repo, view = facts.get("commit_repo"), facts.get("git_view")
        agents = [f for f in facts.get("commit_files", []) if agent_file(f)]
        if agents and repo and not (view and view.is_home(repo)):
            add("unit_commit", ", ".join(agents))
        for path in facts.get("writes", []):
            p = parts(path)
            if ".claude" not in p:
                continue
            below = p[p.index(".claude") + 1:]
            if below[:1] == ["rules"]:
                add("rules", path)
            elif "memory" in below[:-1]:
                add("memory", path)
            elif below == ["project", "behaviors.json"]:
                add("registry", path)
            elif below in (["entry", "boot.py"], ["settings.json"]):
                add("anchor", path)
        for path in facts.get("writes", []):
            p = parts(path)
            if p[-1:] == [".mcp.json"] or (p[-1:] == ["anchor.py"] and beside_harness(path)):
                add("anchor", path)
        return {RULE_ACTIONS: out} if out else {}
