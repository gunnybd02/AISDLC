"""h19.commit-guards: agent files never go into a unit's commit (the home's are its own code); a rule, a memory file or
the behaviour registry is never written by a tool, each refused with its door."""
import unittest

from harness.assemble.engine.ports import GitView
from harness.gear.decide.arbiter import Decide
from harness.gear.detect.agent import AgentFiles
from harness.gear.translate.place import Places
from harness.utils.contracts import Event
from tests import CLAUDE_DIR
from tests.e2e import git_repo


class AgentTest(unittest.TestCase):
    def test_agent_files_never_go_into_a_unit_commit(self):
        unit = git_repo(self, {"a.py": ""})
        view = GitView(git_repo(self, {"x": ""}) / ".claude", ("main",))
        facts = {"commit_repo": str(unit), "commit_files": ["a.py", ".claude/settings.json", "CLAUDE.md"], "git_view": view}
        self.assertEqual([(f.kind, f.detail) for f in AgentFiles().detect(Event("PreToolUse"), facts)],
                         [("commit.agent_files", ".claude/settings.json, CLAUDE.md")])
        home = {**facts, "git_view": GitView(unit / ".claude", ("main",))}
        self.assertEqual(AgentFiles().detect(Event("PreToolUse"), home), [])  # the home commits its own harness
        self.assertEqual(Decide.load(CLAUDE_DIR).rules["commit.agent_files"]["verdict"], "refuse")

    def test_rules_memory_and_registry_files_name_their_door(self):
        rules = Decide.load(CLAUDE_DIR).rules
        for path, kind, door in (("/r/.claude/rules/style.md", "agent.rules", "skill"),
                                 ("/home/u/.claude/projects/p/memory/notes.md", "agent.memory", "note"),
                                 ("/r/.claude/project/behaviors.json", "agent.registry", "add test")):
            with self.subTest(kind=kind):
                event = Event("PreToolUse", "Write", {"file_path": path}, "s1", "/r")
                self.assertEqual([f.kind for f in AgentFiles().detect(event, Places().translate(event))], [kind])
                self.assertEqual(rules[kind]["verdict"], "refuse")
                self.assertIn(door, rules[kind]["why"])
        event = Event("PreToolUse", "Write", {"file_path": "/r/.claude/harness/x.py"}, "s1", "/r")
        self.assertEqual(AgentFiles().detect(event, Places().translate(event)), [])

    def test_the_anchors_of_the_release_are_never_written(self):
        rules = Decide.load(CLAUDE_DIR).rules
        for path in ("/r/.claude/entry/boot.py", "/r/.claude/settings.json", "/r/.mcp.json"):
            with self.subTest(path=path):
                event = Event("PreToolUse", "Write", {"file_path": path}, "s1", "/r")
                self.assertEqual([f.kind for f in AgentFiles().detect(event, Places().translate(event))], ["agent.anchor"])
        self.assertEqual(rules["agent.anchor"]["verdict"], "refuse")
        self.assertIn("live publish", rules["agent.anchor"]["why"])
        event = Event("PreToolUse", "Write", {"file_path": "/r/.claude/entry/hook.py"}, "s1", "/r")
        self.assertEqual(AgentFiles().detect(event, Places().translate(event)), [])  # the gates judge it; publish ships it


if __name__ == "__main__":
    unittest.main()
