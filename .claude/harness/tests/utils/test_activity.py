"""The harness records each action by itself (docs/12-ledger.md): a prompt opens a turn; a judged call leaves a
tool-call row, a gate span and its findings in one transaction, all or none; a recording fault never blocks or changes
a call; nothing secret is stored in clear."""
import contextlib
import io
import sqlite3
import unittest
from unittest import mock

from harness.assemble.engine.build import build_runner
from harness.assemble.engine.ports import LedgerPort
from harness.utils.contracts import CLAUDE_DECISION, REFUSE, Event
from harness.utils.ledger import activity
from harness.utils.ledger.mask import REDACTED, mask, stored
from harness.tests.e2e import copy_tree, git_repo

KEY = "sk-ant-" + "a1B2" * 10  # the shape of an API key, not one


class ActivityTest(unittest.TestCase):
    def setUp(self):
        self.claude_dir = copy_tree(self)
        self.repo = git_repo(self, {"a.py": "X = 1\n"})
        self.port = LedgerPort(self.claude_dir)

    def run_event(self, kind, tool="", tool_input=None, sid="s1"):
        return build_runner(self.claude_dir).run(Event(kind, tool, tool_input or {}, sid, str(self.repo)))

    def rows(self, sql):
        return [tuple(r[k] for k in r.keys()) for r in self.port.rows(sql)]

    def test_a_judged_call_leaves_its_tool_call_its_gate_span_and_its_findings(self):
        self.run_event("UserPromptSubmit", tool_input={"prompt": "set X to 2"})
        refused = self.run_event("PreToolUse", "Write", {"file_path": str(self.repo / "a.py"), "content": "X = 2\n"})
        self.assertEqual(refused.verdict.decision, REFUSE)  # no plan is approved
        self.run_event("PreToolUse", "Read", {"file_path": str(self.repo / "a.py")})
        self.assertEqual(self.rows("SELECT sid, tool, plan_id FROM act_tool_calls ORDER BY rowid"),
                         [("s1", "Write", 0), ("s1", "Read", 0)])
        spans = self.rows("SELECT kind, status, name, turn, done FROM pl_spans ORDER BY rowid")
        self.assertEqual(spans, [("gate", "denied", "Write", 1, 1), ("gate", "ok", "Read", 1, 1)])  # in turn 1
        word = CLAUDE_DECISION[REFUSE]
        self.assertIn(f'"decision": "{word}"', self.rows("SELECT attrs FROM pl_spans ORDER BY rowid")[0][0])
        decisions = self.rows("SELECT tool, verdict FROM act_rule_decisions WHERE verdict = '%s'" % word)
        self.assertEqual(decisions, [("Write", word)])  # each finding with the word Claude Code was given

    def test_a_run_of_a_harness_action_is_recorded_under_its_block_and_action(self):
        event = Event("PreToolUse", activity.RUN_TOOL, {"block": "plan", "action": "plan_show", "args": {"plan": "x"}}, "s1", "/w")
        self.assertEqual(activity.tool_of(event), "plan.plan_show")
        self.assertEqual(activity.tool_of(Event("PreToolUse", "Bash", {"command": "ls"}, "s1", "/w")), "Bash")
        self.assertEqual(activity.arg_names({"plan": "secret value", "a": 1}), ["a", "plan"])
        self.assertEqual(activity.arg_names("not an object"), [])

    def test_a_call_is_recorded_whole_or_not_at_all_and_a_fault_never_blocks_it(self):
        err = io.StringIO()
        with mock.patch.object(activity, "span", side_effect=sqlite3.OperationalError("disk I/O error")), \
                contextlib.redirect_stderr(err):
            out = self.run_event("PreToolUse", "Write", {"file_path": str(self.repo / "a.py"), "content": "X = 2\n"})
        self.assertEqual(out.verdict.decision, REFUSE)  # the call is judged and answered as ever
        self.assertIn("not recorded in the ledger (PreToolUse Write): OperationalError: disk I/O error", err.getvalue())
        self.assertEqual(self.rows("SELECT COUNT(*) FROM act_tool_calls"), [(0,)])  # none of its rows was kept
        self.assertEqual(self.rows("SELECT COUNT(*) FROM act_rule_decisions"), [(0,)])

    def test_a_prompt_opens_a_turn_and_the_end_of_the_reply_closes_it(self):
        self.run_event("UserPromptSubmit", tool_input={"prompt": "first"})
        self.run_event("UserPromptSubmit", tool_input={"prompt": ""})  # an empty prompt: a turn, no text
        peer = activity.PEER + ' from-session="x">do it</cross-session-message>'
        self.run_event("UserPromptSubmit", tool_input={"prompt": peer})
        turns = self.rows("SELECT n, prompt_len, ended_at > 0 FROM pl_turns ORDER BY n")
        self.assertEqual(turns, [(1, 5, 1), (2, 0, 1), (3, len(peer), 0)])  # a new prompt closes the turn before
        self.assertEqual(self.rows("SELECT n, text, from_peer, source FROM pl_prompts ORDER BY n"),
                         [(1, "first", 0, "live"), (3, peer, 1, "live")])
        self.run_event("Stop")
        self.assertEqual(self.rows("SELECT n FROM pl_turns WHERE ended_at = 0"), [])
        self.assertEqual(activity.turn_now(self.port.ledger.con, "s1"), 3)
        self.assertEqual(activity.turn_now(self.port.ledger.con, "other"), 0)

    def test_a_turn_follows_the_prompts_of_a_ledger_made_before_turns_were_kept(self):
        self.port.write(lambda con, rec: con.execute(
            "INSERT INTO pl_prompts (sid, n, text, chars, cut, from_peer, source, uuid, at) VALUES ('s1', 4, 'old', 3, 0, 0, 'user', '', 1)"))
        self.run_event("UserPromptSubmit", tool_input={"prompt": "new"})
        self.assertEqual(self.rows("SELECT n, text FROM pl_prompts ORDER BY n"), [(4, "old"), (5, "new")])

    def test_nothing_secret_is_stored_in_clear_and_a_long_text_is_cut(self):
        self.assertEqual(mask(f"line one\ntoken {KEY}\nline three"), f"line one\n{REDACTED}\nline three")
        self.assertEqual(mask(None), "")
        self.assertEqual(stored("x" * 10, 4), ("xxxx", 10, 1))
        self.assertEqual(stored("short", 10), ("short", 5, 0))
        long = "y" * (activity.PROMPT_MOST + 5)
        self.run_event("UserPromptSubmit", tool_input={"prompt": f"use {KEY} now"})
        self.run_event("UserPromptSubmit", tool_input={"prompt": long})
        rows = self.rows("SELECT text, chars, cut FROM pl_prompts ORDER BY n")
        self.assertEqual(rows[0], (REDACTED, len(REDACTED), 0))
        self.assertEqual((len(rows[1][0]), rows[1][1], rows[1][2]), (activity.PROMPT_MOST, len(long), 1))


if __name__ == "__main__":
    unittest.main()
