"""h17.cli-tool: a session whose Claude Code has no harness MCP server (a cloud session started before its setup script
installed it) reaches the same tools from the shell: boot.py cli tool find|guide|run. The hook links the session that
runs the command, a refusal that names run(...) says how, and a write action is judged as through the MCP server."""
import json
import re
import shlex
import unittest

from harness.assemble.engine.build import with_hint
from harness.gear.translate.place import Places
from harness.utils.contracts import Event
from tests.e2e import copy_tree, git_repo, run
from tests.e2e.test_flow import CONFIG, Flow

PLAN = {"plan": {"title": "Set X", "what": ["X becomes 2"], "files": ["a.py"], "tests": ["test_a.py"]}}


class CliToolTest(unittest.TestCase):
    def setUp(self):
        self.claude_dir = copy_tree(self, {"project.json": json.dumps(CONFIG)})
        self.repo = git_repo(self, {"a.py": "X = 1\n", "test_a.py": "", "b.py": ""})
        self.flow = Flow(self.claude_dir, self.repo)
        self.boot = (self.claude_dir / "entry" / "boot.py").as_posix()

    def shell(self, *words):
        """The model's shell line for the tool door: the hook sees it first, then it runs in the repository."""
        line = shlex.join(["python3", self.boot, "cli", "tool", *words])
        decision = self.flow.decision("Bash", {"command": line, "description": "harness tool"})
        code, out, err = run(self.claude_dir / "entry" / "boot.py", args=("cli", "tool", *words), cwd=self.repo)
        return decision, code, out + err

    def test_a_plan_is_presented_and_approved_without_the_mcp_server(self):
        refusal = self.flow.hook("PreToolUse", "Write", {"file_path": str(self.repo / "a.py"), "content": "X = 2\n"})
        self.assertEqual(refusal["permissionDecision"], "deny")
        self.assertIn(f'python3 "{self.boot}" cli tool run <block> <action>', refusal["permissionDecisionReason"])

        decision, code, out = self.shell("guide", "plan")
        self.assertEqual((decision, code), ("allow", 0))
        self.assertIn("plan_present", out)

        decision, code, out = self.shell("run", "plan", "plan_present", json.dumps(PLAN))
        self.assertEqual((decision, code), ("allow", 0), out)
        q = re.search(r'Duy\u1ec7t plan "Set X" \((pd-[0-9a-z]+-[0-9a-f]{6}) rev 1\)\?', out)
        self.assertIsNotNone(q, out)
        options = [{"label": "Duy\u1ec7t"}, {"label": "S\u1eeda plan"}]
        form = {"questions": [{"question": q.group(0), "options": options}]}
        note = self.flow.hook("PostToolUse", "AskUserQuestion", form, {"answers": {q.group(0): "Duy\u1ec7t"}})
        self.assertIn("approved", note["additionalContext"])  # the plan was kept for this session: "flow"
        self.assertEqual(self.flow.decision("Write", {"file_path": str(self.repo / "a.py"), "content": "X = 2\n"}),
                         "allow")

    def test_a_write_action_is_judged_and_bad_arguments_are_refused(self):
        _, code, out = self.shell("run", "plan", "step_done", json.dumps({"message": "Set X"}))
        self.assertEqual(code, 1)
        self.assertNotIn("committed", out)
        for args in ("{not json", "[1]"):
            _, code, out = self.shell("run", "plan", "plan_present", args)
            self.assertEqual(code, 1)
            self.assertIn("refused", out)
        _, code, out = self.shell("run", "plan", "no_such")
        self.assertEqual(code, 1)
        self.assertIn("No action plan.no_such", out)

    def test_the_hook_links_only_a_line_that_runs_the_harness(self):
        def facts(command):
            return Places().translate(Event("PreToolUse", "Bash", {"command": command}, "s", str(self.repo)))
        self.assertTrue(facts(f"python3 {self.boot} cli tool guide plan").get("harness_cli"))
        self.assertTrue(facts("cd .claude && python3 -m entry.cli verify").get("harness_cli"))
        self.assertFalse(facts("python3 a.py").get("harness_cli"))
        self.assertEqual(with_hint("No plan.", self.claude_dir), "No plan.")


if __name__ == "__main__":
    unittest.main()
