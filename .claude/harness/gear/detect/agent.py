"""AgentFiles: what agent files never take.
- commit.agent_files: a commit of a unit (any repository but the home, which holds the harness) holds agent files
  (.claude/, CLAUDE.md, CLAUDE.local.md, .mcp.json, AGENTS.md);
- agent.rules: a write into a .claude/rules/ folder (a rule is a skill: project/skills/);
- agent.memory: a write into a memory/ folder of .claude (a point to keep is a note, kept in SQL);
- agent.registry: a write to the behaviour registry file (.claude/project/behaviors.json: add test, behaviors add);
- agent.anchor: a write to what decides which code a session runs: anchor.py beside a .claude that holds a harness,
  .claude/entry/boot.py (the forwarder of the old path), .claude/settings.json, or the .mcp.json beside .claude (the
  user changes them outside a session);
- agent.session_start: a shell line that runs the SessionStart entry, which puts the newest main in force without the
  user's word: only Claude Code runs it, when a session begins (in a session: live update and the form)."""
import os

from harness.gear.detect.git import agent_file
from harness.utils.contracts import Detector, Finding


def beside_harness(path):
    """Whether the file sits beside a .claude folder that holds a harness: the root of a core repository."""
    return os.path.isdir(os.path.join(os.path.dirname(str(path)), ".claude", "harness"))


def parts(path):
    return [p.lower() for p in str(path).replace("\\", "/").split("/") if p]


class AgentFiles(Detector):
    def detect(self, event, facts):
        out = []
        if event.kind == "PreToolUse" and facts.get("harness_session_start"):
            out.append(Finding("agent.session_start", event.input.get("command", "")))
        repo, view = facts.get("commit_repo"), facts.get("git_view")
        agents = [f for f in facts.get("commit_files", []) if agent_file(f)]
        if agents and repo and not (view and view.is_home(repo)):
            out.append(Finding("commit.agent_files", ", ".join(agents)))
        for path in facts.get("writes", []):
            p = parts(path)
            if ".claude" not in p:
                continue
            below = p[p.index(".claude") + 1:]
            if below[:1] == ["rules"]:
                out.append(Finding("agent.rules", path))
            elif "memory" in below[:-1]:
                out.append(Finding("agent.memory", path))
            elif below == ["project", "behaviors.json"]:
                out.append(Finding("agent.registry", path))
            elif below in (["entry", "boot.py"], ["settings.json"]):
                out.append(Finding("agent.anchor", path))
        for path in facts.get("writes", []):
            p = parts(path)
            if p[-1:] == [".mcp.json"] or (p[-1:] == ["anchor.py"] and beside_harness(path)):
                out.append(Finding("agent.anchor", path))
        return out
