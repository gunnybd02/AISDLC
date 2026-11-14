"""h11.one-flow: one whole flow through the new harness, as Claude Code runs it: the hook and the MCP server are
processes of their own, on a real git repository: plan -> form -> edit -> verify -> commit -> ledger -> delivered."""
import json
import re
import subprocess
import unittest

from harness.utils.ledger.db import Ledger
from harness.utils.ledger.recorder import Recorder
from tests.e2e import copy_tree, git_repo, run

CONFIG = {"name": "flow", "verify": ["{python}", "-m", "unittest", "discover", "-s", "."]}
TEST_A = "import unittest\n\nimport a\n\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(a.X, 2)\n"


class Flow:
    def __init__(self, claude_dir, repo):
        self.claude_dir, self.repo = claude_dir, repo

    def hook(self, kind, tool, tool_input, response=None):
        payload = {"hook_event_name": kind, "tool_name": tool, "tool_input": tool_input, "session_id": "flow",
                   "cwd": str(self.repo)}
        if response is not None:
            payload["tool_response"] = response
        code, out, err = run(self.claude_dir / "entry" / "hook.py", json.dumps(payload))
        if code == 2:  # what Claude Code reads as a block, with err as the reason
            return {"permissionDecision": "deny", "permissionDecisionReason": err}
        assert code == 0, err
        return json.loads(out)["hookSpecificOutput"] if out else {}

    def decision(self, tool, tool_input):
        return self.hook("PreToolUse", tool, tool_input).get("permissionDecision", "allow")

    def mcp(self, block, action, args=None):
        line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "run", "arguments": {"block": block, "action": action, "args": args or {}}}})
        # Claude Code starts the MCP server in the project's folder: the plan's root
        code, out, err = run(self.claude_dir / "entry" / "mcp_server.py", line + "\n", cwd=self.repo)
        assert code == 0, err
        return json.loads(out)["result"]["content"][0]["text"]


class OneFlowTest(unittest.TestCase):
    def test_plan_to_delivery(self):
        claude_dir = copy_tree(self, {"project.json": json.dumps(CONFIG)})
        repo = git_repo(self, {"a.py": "X = 1\n", "test_a.py": TEST_A.replace("2", "1"), "b.py": ""})
        flow = Flow(claude_dir, repo)
        write_a = {"file_path": str(repo / "a.py"), "content": "X = 2\n"}

        # no plan: no edit
        self.assertEqual(flow.decision("Write", write_a), "deny")

        # the plan, and the form the user answers
        out = flow.mcp("plan", "plan_present", {"plan": {"title": "Set X", "files": ["a.py"], "tests": ["test_a.py"]}})
        q = re.search(r'Duyệt plan "Set X" \((pd-\w+) rev 1\): [^\n]*?\?(?= Options)', out)
        plan_id = q.group(1)
        self.assertIn("a.py, test_a.py", q.group(0))
        form = {"questions": [{"question": q.group(0), "options": [{"label": "Duyệt"}, {"label": "Sửa plan"}]}]}
        self.assertEqual(flow.decision("AskUserQuestion", {**form, "answers": {q.group(0): "Duyệt"}}), "deny")
        self.assertEqual(flow.decision("AskUserQuestion", form), "allow")
        note = flow.hook("PostToolUse", "AskUserQuestion", form, {"answers": {q.group(0): "Duyệt"}})
        self.assertIn("approved", note["additionalContext"])

        # edits: the plan's files only
        self.assertEqual(flow.decision("Write", write_a), "allow")
        self.assertEqual(flow.decision("Write", {"file_path": str(repo / "b.py"), "content": "x"}), "deny")
        (repo / "a.py").write_text("X = 2\n", encoding="utf-8")
        (repo / "test_a.py").write_text(TEST_A, encoding="utf-8")

        # commit: never from the shell; step_done refuses before the verify and commits after it
        self.assertEqual(flow.decision("Bash", {"command": "git commit -m 'Set X'"}), "deny")
        self.assertIn("no passing verify", flow.mcp("steps", "step_done", {"plan": plan_id, "message": "Set X"}))
        self.assertIn("verify passed", flow.mcp("verify", "run", {"plan": plan_id}))
        self.assertIn("delivered", flow.mcp("steps", "step_done", {"plan": plan_id, "message": "Set X"}))

        # delivered: a new edit needs a new plan
        self.assertEqual(flow.decision("Write", write_a), "deny")

        # the ledger holds the whole story, chained rows unbroken
        ledger = Ledger.open(claude_dir / "state" / "harness.db")
        events = [r["event"] for r in ledger.all("SELECT event FROM pl_plan_events WHERE plan_id = ? ORDER BY n",
                                                 (plan_id,))]
        self.assertEqual(events, ["waiting", "approved", "delivered"])
        self.assertEqual(ledger.one("SELECT ok FROM pl_verify")["ok"], 1)
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
        self.assertEqual(ledger.one("SELECT commit_sha FROM rec_commits")["commit_sha"], head.strip())
        rules = {r["rule"] for r in ledger.all("SELECT rule FROM act_rule_decisions")}
        self.assertLessEqual({"plan.none", "plan.outside", "commit.raw"}, rules)
        for table in ("rec_plans", "rec_commits", "pl_verify"):
            self.assertTrue(Recorder.chain_ok(ledger, table), table)
        ledger.close()


if __name__ == "__main__":
    unittest.main()
