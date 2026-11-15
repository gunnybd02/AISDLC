"""h23.one-core: a repository's own wiring (boot.py ... --project) is the harness when none is installed for the user;
when one is (entry/install.py), that one is the core and the repository's copy gives way: its hook does nothing and its
MCP server is the core's, so a clone of the harness being worked on never keeps a second ledger."""
import json
import sys
import unittest

from harness.assemble.engine.cli_install import install
from harness.assemble.engine.ports import LedgerPort
from tests import tree
from tests.e2e import copy_tree, git_repo, run

PLAN = {"plan": {"title": "Set X", "what": ["X becomes 2"], "files": ["a.py"], "tests": []}}


def call(block, action, args):
    return json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "run", "arguments": {"block": block, "action": action, "args": args}}}) + "\n"


class OneCoreTest(unittest.TestCase):
    def setUp(self):
        self.clone = copy_tree(self)  # the repository's own copy: what its settings.json and .mcp.json run
        self.repo = git_repo(self, {"a.py": "X = 1\n"})
        self.user = tree(self, {})  # the user's ~/.claude
        self.env = {"CLAUDE_CONFIG_DIR": str(self.user)}

    def hook(self, home, kind, tool, tool_input, project=True):
        payload = json.dumps({"hook_event_name": kind, "tool_name": tool, "tool_input": tool_input,
                              "session_id": "s1", "cwd": str(self.repo)})
        return run(home / "entry" / "boot.py", payload, args=("hook", "--project") if project else ("hook",),
                   env=self.env)

    def write(self, home, project=True):
        return self.hook(home, "PreToolUse", "Write", {"file_path": str(self.repo / "a.py"), "content": "X = 2\n"},
                         project)

    def present(self, home):
        code, out, err = run(home / "entry" / "boot.py", call("plan", "plan_present", PLAN),
                             args=("mcp_server", "--project"), env=self.env, cwd=self.repo)
        self.assertEqual(code, 0, err)
        return json.loads(out)["result"]["content"][0]["text"]

    def test_with_no_harness_installed_the_repository_copy_is_the_core(self):
        code, out, _ = self.write(self.clone)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")  # it judges
        self.hook(self.clone, "UserPromptSubmit", "", {})
        self.assertIn("waits for the user's approval", self.present(self.clone))
        self.assertEqual(len(LedgerPort(self.clone).waiting()), 1)  # kept in its own ledger

    def test_with_a_harness_installed_the_repository_copy_gives_way(self):
        core = copy_tree(self)
        install(core, self.user, self.user / "claude.json", sys.executable, use_cli=False)
        self.assertEqual(self.write(self.clone)[:2], (0, ""))  # the copy's hook says nothing
        code, out, _ = self.write(core, project=False)  # the core's own hook, as the user's settings run it
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.hook(core, "UserPromptSubmit", "", {}, project=False)
        self.assertIn("waits for the user's approval", self.present(self.clone))  # the copy's .mcp.json entry
        self.assertEqual(len(LedgerPort(core).waiting()), 1)  # the plan is in the core's ledger
        self.assertFalse((self.clone / "state" / "harness.db").exists())  # the copy keeps none

    def test_an_installed_harness_run_by_its_own_repository_wiring_judges_once(self):
        install(self.clone, self.user, self.user / "claude.json", sys.executable, use_cli=False)
        self.assertEqual(self.write(self.clone)[:2], (0, ""))  # the project hook gives way to the user's hook
        code, out, _ = self.write(self.clone, project=False)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.hook(self.clone, "UserPromptSubmit", "", {}, project=False)
        self.assertIn("waits for the user's approval", self.present(self.clone))  # its own server, no hand-over

    def test_settings_that_name_no_harness_leave_the_repository_copy_the_core(self):
        for text in ("[1]", "{not json", json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command":
                     '"python3" "/gone/.claude/entry/boot.py" hook'}]}]}})):
            with self.subTest(settings=text):
                (self.user / "settings.json").write_text(text, encoding="utf-8")
                code, out, _ = self.write(self.clone)
                self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
