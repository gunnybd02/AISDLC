"""h22.install: the harness installs for every session of a user: its hooks merged into the user's settings, its CLI
allowed in the user's permissions, and its MCP server at user scope; running it again changes nothing; uninstall takes
out only what it put in."""
import json
import unittest
from pathlib import Path

from harness.assemble.engine.cli_install import allow_rules, install, uninstall
from tests import CLAUDE_DIR, tree
from tests.e2e import run

MINE = {"type": "command", "command": "echo mine"}
MY_RULE = "Bash(npm test:*)"


class InstallTest(unittest.TestCase):
    def setUp(self):
        mine = {"PreToolUse": [{"matcher": "Bash", "hooks": [MINE]}]}
        self.user = tree(self, {"settings.json": json.dumps({"theme": "dark", "permissions": {"allow": [MY_RULE]},
                                                             "hooks": mine})})
        self.claude_json = self.user / "claude.json"
        self.claude_json.write_text(json.dumps({"numStartups": 7, "mcpServers": {"other": {"command": "x"}}}))
        self.boot = str((CLAUDE_DIR / "entry" / "boot.py").resolve())

    def settings(self):
        return json.loads((self.user / "settings.json").read_text())

    def go(self):
        return install(CLAUDE_DIR, self.user, self.claude_json, "python3", use_cli=False)

    def test_install_merges_hooks_and_the_server_and_runs_again_safely(self):
        self.assertIn("run under the harness", self.go())
        data = self.settings()
        self.assertEqual(data["theme"], "dark")
        self.assertIn(MINE, data["hooks"]["PreToolUse"][0]["hooks"])  # the user's own hook stays
        for event in ("PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop"):
            with self.subTest(event=event):
                commands = [h["command"] for g in data["hooks"][event] for h in g["hooks"]]
                self.assertEqual(sum(self.boot in c for c in commands), 1)
        servers = json.loads(self.claude_json.read_text())
        self.assertEqual(servers["numStartups"], 7)
        self.assertEqual(servers["mcpServers"]["harness"]["args"], [self.boot, "mcp_server"])
        self.assertIn("other", servers["mcpServers"])
        allow = data["permissions"]["allow"]
        self.assertEqual(allow[0], MY_RULE)  # the user's own rule stays
        self.assertIn(f'Bash(python3 "{Path(self.boot).as_posix()}" cli:*)', allow)  # the form refusals give
        self.assertIn(f'Bash("python3" "{self.boot}" cli:*)', allow)
        self.assertTrue(all(r.endswith(" cli:*)") for r in allow[1:]))
        self.go()
        self.assertEqual(self.settings(), data)  # again: nothing more

    def test_uninstall_takes_out_only_what_install_put_in(self):
        self.go()
        self.assertIn("Removed", uninstall(CLAUDE_DIR, self.user, self.claude_json, use_cli=False))
        data = self.settings()
        self.assertEqual(data["hooks"]["PreToolUse"], [{"matcher": "Bash", "hooks": [MINE]}])
        self.assertEqual(data["hooks"]["Stop"], [])
        self.assertEqual(data["permissions"]["allow"], [MY_RULE])
        self.assertEqual(json.loads(self.claude_json.read_text())["mcpServers"], {"other": {"command": "x"}})

    def test_a_harness_under_the_users_home_is_also_allowed_from_tilde(self):
        boot = Path("/home/u/.harness/.claude/entry/boot.py")
        rules = allow_rules("/usr/bin/python3", boot, Path("/home/u"))
        self.assertIn("Bash(python3 ~/.harness/.claude/entry/boot.py cli:*)", rules)
        self.assertNotIn("~", " ".join(allow_rules("/usr/bin/python3", boot, Path("/srv"))))
        self.assertTrue(all(r.startswith("Bash(") and r.endswith(" cli:*)") for r in rules))

    def test_a_settings_file_that_is_not_an_object_is_left_alone(self):
        (self.user / "settings.json").write_text("[1]")
        with self.assertRaises(ValueError):
            self.go()
        self.assertEqual((self.user / "settings.json").read_text(), "[1]")

    def test_the_entry_installs_from_a_terminal(self):
        code, out, _ = run(CLAUDE_DIR / "entry" / "install.py", args=(
            "--user-dir", str(self.user), "--claude-json", str(self.claude_json), "--no-cli"))
        self.assertEqual(code, 0, out)
        self.assertIn("harness", json.loads(self.claude_json.read_text())["mcpServers"])


if __name__ == "__main__":
    unittest.main()
