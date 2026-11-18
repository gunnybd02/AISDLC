"""h11.one-flow: one whole flow through the new harness, as Claude Code runs it: the hook and the MCP server are
processes of their own, on a real git repository: plan -> form -> edit -> verify -> commit -> ledger -> delivered."""
import json
import re
import subprocess
import unittest

from harness.utils.ledger.db import Ledger
from harness.utils.ledger.recorder import Recorder
from harness.tests import entry_of
from harness.tests.e2e import copy_tree, git_repo, run

REPOS = {"flow": {"url": "https://github.com/acme/flow", "verify": ["{python}", "-m", "unittest", "discover", "-s", "."]}}
TEST_A = "import unittest\n\nimport a\n\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(a.X, 2)\n"


def flow_repo(test, files):
    """A git repository whose origin is the repo REPOS names: a plan with those repos may work in it."""
    repo = git_repo(test, files)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", REPOS["flow"]["url"] + ".git"], check=True,
                   capture_output=True)
    return repo


class Flow:
    def __init__(self, claude_dir, repo):
        self.claude_dir, self.repo = claude_dir, repo

    def hook(self, kind, tool, tool_input, response=None):
        payload = {"hook_event_name": kind, "tool_name": tool, "tool_input": tool_input, "session_id": "flow",
                   "cwd": str(self.repo)}
        if response is not None:
            payload["tool_response"] = response
        code, out, err = run(entry_of(self.claude_dir, "hook"), json.dumps(payload))
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
        code, out, err = run(entry_of(self.claude_dir, "mcp_server"), line + "\n", cwd=self.repo)
        assert code == 0, err
        return json.loads(out)["result"]["content"][0]["text"]


class OneFlowTest(unittest.TestCase):
    def test_plan_to_delivery(self):
        claude_dir = copy_tree(self)
        repo = flow_repo(self, {"a.py": "X = 1\n", "test_a.py": TEST_A.replace("2", "1"), "b.py": ""})
        flow = Flow(claude_dir, repo)
        write_a = {"file_path": str(repo / "a.py"), "content": "X = 2\n"}

        # no plan: no edit
        self.assertEqual(flow.decision("Write", write_a), "deny")

        # the plan, and the form the user answers
        flow.hook("UserPromptSubmit", "", {})  # the session the MCP server works for
        out = flow.mcp("plan", "plan_present", {"plan": {"title": "Set X", "what": ["X becomes 2"], "files": ["a.py"],
                                                         "tests": ["test_a.py"], "repos": REPOS}})
        q = re.search(r'Approve plan "Set X" \((pd-[0-9a-z]+-[0-9a-f]{6}) rev 1\)\?(?= Header)', out)
        plan_id = q.group(1)
        self.assertIn("## Plan\nRepos:\n- flow: https://github.com/acme/flow | base main | verify: {python} -m unittest "
                      "discover -s .\nServices: agent-code\nWhat: X becomes 2\nFiles: a.py\nTests: test_a.py", out)
        form = {"questions": [{"question": q.group(0), "options": [{"label": "Approve"}, {"label": "Change plan"}]}]}
        self.assertEqual(flow.decision("AskUserQuestion", {**form, "answers": {q.group(0): "Approve"}}), "deny")
        self.assertEqual(flow.decision("AskUserQuestion", form), "allow")
        note = flow.hook("PostToolUse", "AskUserQuestion", form, {"answers": {q.group(0): "Approve"}})
        self.assertIn("approved", note["additionalContext"])

        # edits: the plan's files only
        self.assertEqual(flow.decision("Write", write_a), "allow")
        self.assertEqual(flow.decision("Write", {"file_path": str(repo / "b.py"), "content": "x"}), "deny")
        (repo / "a.py").write_text("X = 2\n", encoding="utf-8")
        (repo / "test_a.py").write_text(TEST_A, encoding="utf-8")

        # commit: never from the shell; step_done refuses before the verify and commits after it
        self.assertEqual(flow.decision("Bash", {"command": "git commit -m 'Set X'"}), "deny")
        self.assertIn("no green verify", flow.mcp("plan", "step_done", {"message": "Set X"}))
        self.assertIn("verify passed", flow.mcp("verify", "run", {"plan": plan_id}))
        self.assertIn("delivered", flow.mcp("plan", "step_done", {"message": "Set X"}))

        # delivered: a new edit needs a new plan
        self.assertEqual(flow.decision("Write", write_a), "deny")

        # the ledger holds the whole story, chained rows unbroken
        ledger = Ledger.open(claude_dir / "state" / "harness.db")
        events = [r["event"] for r in ledger.all("SELECT event FROM pl_plan_events WHERE plan_id = ? ORDER BY n",
                                                 (plan_id,))]
        self.assertEqual(events, ["waiting", "approved", "executing", "delivered"])
        self.assertEqual(ledger.one("SELECT ok FROM pl_verify")["ok"], 1)
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
        self.assertEqual(ledger.one("SELECT commit_sha FROM rec_commits")["commit_sha"], head.strip())
        rules = {r["rule"] for r in ledger.all("SELECT rule FROM act_rule_decisions")}
        self.assertLessEqual({"plan.none", "plan.outside", "commit.raw"}, rules)
        for table in ("rec_plans", "rec_commits", "pl_verify"):
            self.assertTrue(Recorder.chain_ok(ledger, table), table)
        ledger.close()


class RecordedFlowTest(unittest.TestCase):
    def test_the_hook_entry_records_turns_prompts_and_calls_by_itself(self):
        claude_dir = copy_tree(self)
        repo = git_repo(self, {"a.py": "X = 1\n"})
        flow = Flow(claude_dir, repo)
        key = "ghp_" + "a1B2c3D4" * 5  # the shape of a token, not one
        flow.hook("UserPromptSubmit", "", {})  # Claude Code sends the prompt beside the input, read below
        payload = {"hook_event_name": "UserPromptSubmit", "session_id": "flow", "cwd": str(repo), "prompt": f"push with {key}"}
        self.assertEqual(run(entry_of(claude_dir, "hook"), json.dumps(payload))[0], 0)
        self.assertEqual(flow.decision("Read", {"file_path": str(repo / "a.py")}), "allow")
        self.assertEqual(flow.decision("Write", {"file_path": str(repo / "a.py"), "content": "X = 2\n"}), "deny")
        flow.hook("Stop", "", {})
        ledger = Ledger.open(claude_dir / "state" / "harness.db")
        self.addCleanup(ledger.close)
        turns = [tuple(r[k] for k in r.keys()) for r in ledger.all("SELECT n, ended_at > 0 FROM pl_turns WHERE sid = 'flow' ORDER BY n")]
        self.assertEqual(turns[-1][1], 1)  # the end of the reply closed the last turn
        prompts = [r["text"] for r in ledger.all("SELECT text FROM pl_prompts WHERE sid = 'flow'")]
        self.assertEqual(prompts, ["[redacted]"])  # a prompt that holds a token is not stored in clear
        calls = [r["tool"] for r in ledger.all("SELECT tool FROM act_tool_calls WHERE sid = 'flow' ORDER BY rowid")]
        self.assertEqual(calls, ["Read", "Write"])
        spans = [(r["name"], r["status"], r["turn"]) for r in ledger.all("SELECT name, status, turn FROM pl_spans ORDER BY rowid")]
        self.assertEqual(spans, [("Read", "ok", turns[-1][0]), ("Write", "denied", turns[-1][0])])


if __name__ == "__main__":
    unittest.main()
