"""h23.one-core: a repository's own wiring (boot.py ... --project) is the harness when none is installed for the user;
when one is (entry/install.py), that one is the core and the repository's copy gives way: its hook does nothing and its
MCP server is the core's, so a clone of the harness being worked on never keeps a second ledger."""
import json
import sys
import unittest

from harness.assemble.engine.cli_install import install
from harness.assemble.engine.ports import LedgerPort
from harness.utils.gateway.release import build, publish
from harness.tests import anchor_of, tree
from harness.tests.e2e import copy_tree, git_repo, run

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
        return run(anchor_of(home), payload, args=("hook", "--project") if project else ("hook",),
                   env=self.env)

    def write(self, home, project=True):
        return self.hook(home, "PreToolUse", "Write", {"file_path": str(self.repo / "a.py"), "content": "X = 2\n"},
                         project)

    def present(self, home):
        code, out, err = run(anchor_of(home), call("plan", "plan_present", PLAN),
                             args=("mcp_server", "--project"), env=self.env, cwd=self.repo)
        self.assertEqual(code, 0, err)
        return json.loads(out)["result"]["content"][0]["text"]

    def test_with_no_harness_installed_the_repository_copy_is_the_core(self):
        code, out, _ = self.write(self.clone)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")  # it judges
        self.hook(self.clone, "UserPromptSubmit", "", {})
        self.assertIn("is waiting for the user's approval", self.present(self.clone))
        self.assertEqual(len(LedgerPort(self.clone).waiting()), 1)  # kept in its own ledger

    def test_with_a_harness_installed_the_repository_copy_gives_way(self):
        core = copy_tree(self)
        install(core, self.user, self.user / "claude.json", sys.executable, use_cli=False)
        self.assertEqual(self.write(self.clone)[:2], (0, ""))  # the copy's hook says nothing
        code, out, _ = self.write(core, project=False)  # the core's own hook, as the user's settings run it
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.hook(core, "UserPromptSubmit", "", {}, project=False)
        self.assertIn("is waiting for the user's approval", self.present(self.clone))  # the copy's .mcp.json entry
        self.assertEqual(len(LedgerPort(core).waiting()), 1)  # the plan is in the core's ledger
        self.assertFalse((self.clone / "state" / "harness.db").exists())  # the copy keeps none

    def test_an_installed_harness_run_by_its_own_repository_wiring_judges_once(self):
        install(self.clone, self.user, self.user / "claude.json", sys.executable, use_cli=False)
        self.assertEqual(self.write(self.clone)[:2], (0, ""))  # the project hook gives way to the user's hook
        code, out, _ = self.write(self.clone, project=False)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.hook(self.clone, "UserPromptSubmit", "", {}, project=False)
        self.assertIn("is waiting for the user's approval", self.present(self.clone))  # its own server, no hand-over

    def test_settings_that_name_no_harness_leave_the_repository_copy_the_core(self):
        for text in ("[1]", "{not json", json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command":
                     '"python3" "/gone/.claude/entry/boot.py" hook'}]}]}})):
            with self.subTest(settings=text):
                (self.user / "settings.json").write_text(text, encoding="utf-8")
                code, out, _ = self.write(self.clone)
                self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_a_machine_set_up_before_the_anchor_keeps_working(self):
        old = self.clone / "entry" / "boot.py"  # what its hooks and MCP server still name
        payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Write", "session_id": "s1",
                              "cwd": str(self.repo), "tool_input": {"file_path": str(self.repo / "a.py")}})
        code, out, err = run(old, payload, args=("hook",), env=self.env)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")  # forwarded, it judges
        self.assertIn("0 errors", run(self.clone / "entry" / "doctor.py", env=self.env)[1])  # as its release check runs
        code, out, _ = run(self.clone / "entry" / "install.py", env=self.env, args=(
            "--user-dir", str(self.user), "--claude-json", str(self.user / "claude.json"), "--no-cli"))
        self.assertEqual(code, 0, out)
        self.assertIn(str(anchor_of(self.clone).resolve()), (self.user / "settings.json").read_text())

    def test_a_core_installed_under_the_old_path_is_still_the_core(self):
        core = copy_tree(self)
        install(core, self.user, self.user / "claude.json", sys.executable, use_cli=False)
        settings = self.user / "settings.json"
        old = str((core / "entry" / "boot.py").resolve())
        settings.write_text(settings.read_text().replace(str(anchor_of(core).resolve()), old), encoding="utf-8")
        self.assertIn("boot.py", settings.read_text())
        self.assertEqual(self.write(self.clone)[:2], (0, ""))  # the copy gives way to it
        run(old, json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "cwd": str(self.repo)}),
            args=("hook",), env=self.env)
        self.assertIn("is waiting for the user's approval", self.present(self.clone))
        self.assertEqual(len(LedgerPort(core).waiting()), 1)  # in the core's ledger, through its old path

    def test_a_release_built_before_the_entries_moved_still_runs(self):
        sha = build(self.clone)
        publish(self.clone, sha)
        release = self.clone / "state" / "live" / sha
        (release / "harness" / "entry" / "doctor.py").unlink()
        (release / "entry" / "doctor.py").write_text("print('the doctor of an old release')\n", encoding="utf-8")
        code, out, err = run(anchor_of(self.clone), args=("doctor",), env=self.env)
        self.assertEqual((code, out.strip()), (0, "the doctor of an old release"), err)


if __name__ == "__main__":
    unittest.main()
