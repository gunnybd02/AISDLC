"""Tokens and cost are recorded from a session's transcript (docs/12-ledger.md): one usage row per message and token
type, once; the offset moves; the session's model and effort; an llm span per message; the retro views give tokens
and cost from list prices."""
import json
import os
import unittest
from unittest import mock

from harness.assemble.engine.build import build_runner
from harness.assemble.engine.ports import LedgerPort
from harness.hooks.io import HookIO
from harness.utils.contracts import Event
from harness.utils.ledger import usage
from harness.tests import tree
from harness.tests.e2e import copy_tree, git_repo
from harness.tests.mcp import caller


def reply(mid, model="claude-opus-5-5", at="2026-11-16T10:00:00.000Z", effort="high", **used):
    """One transcript line of a reply of the model, as Claude Code writes it."""
    return json.dumps({"type": "assistant", "timestamp": at, "effort": effort, "sessionId": "s1",
                       "message": {"id": mid, "model": model, "role": "assistant", "content": [], "usage": used}})


LINES = [
    json.dumps({"type": "user", "timestamp": "2026-11-16T09:59:00.000Z", "message": {"role": "user", "content": "hi"}}),
    reply("msg_1", input_tokens=10, output_tokens=5, cache_creation_input_tokens=100, cache_read_input_tokens=0),
    reply("msg_1", input_tokens=10, output_tokens=20, cache_creation_input_tokens=100, cache_read_input_tokens=0),  # same reply, a later block
    "not json at all",
    reply("msg_2", model="claude-haiku-5-5", at="2026-11-16T10:05:00.000Z", effort="low", input_tokens=1000000, output_tokens=0),
]


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.claude_dir = copy_tree(self)
        self.repo = git_repo(self, {"a.py": "X = 1\n"})
        self.port = LedgerPort(self.claude_dir)
        self.folder = tree(self, {})
        self.path = self.folder / "projects" / "p" / "s1.jsonl"
        self.path.parent.mkdir(parents=True)
        self.path.write_text("\n".join(LINES) + "\n", encoding="utf-8")

    def rows(self, sql):
        return [tuple(r[k] for k in r.keys()) for r in self.port.rows(sql)]

    def read(self):
        return self.port.write(lambda con, rec: usage.read_new(con, "s1", self.path))

    def test_new_lines_give_one_row_per_message_and_token_type_once(self):
        self.port.touch_session("s1")
        self.assertEqual(self.read(), 2)
        rows = self.rows("SELECT message_id, token_type, tokens, model, file FROM pl_usage ORDER BY message_id, token_type")
        self.assertEqual(rows, [("msg_1", "cache_write", 100, "claude-opus-5-5", "s1.jsonl"),
                                ("msg_1", "input", 10, "claude-opus-5-5", "s1.jsonl"),
                                ("msg_1", "output", 20, "claude-opus-5-5", "s1.jsonl"),  # the usage of its last line
                                ("msg_2", "input", 1000000, "claude-haiku-5-5", "s1.jsonl")])  # a count of 0 keeps no row
        self.assertEqual(self.read(), 0)  # read again: nothing new, nothing twice
        self.assertEqual(self.rows("SELECT COUNT(*) FROM pl_usage"), [(4,)])
        self.assertEqual(self.rows("SELECT offset FROM pl_usage_offsets WHERE sid = 's1'"), [(os.path.getsize(self.path),)])
        self.assertEqual(self.rows("SELECT model, effort FROM pl_session_meta"), [("claude-haiku-5-5", "low")])  # the last
        self.assertEqual(self.rows("SELECT kind, status, name FROM pl_spans ORDER BY at"),
                         [("llm", "ok", "claude-opus-5-5"), ("llm", "ok", "claude-haiku-5-5")])
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(reply("msg_3", at="2026-11-16T10:06:00.000Z", input_tokens=7, output_tokens=3) + "\n")
            f.write(reply("msg_4", input_tokens=1)[:40])  # a half-written last line waits
        self.assertEqual(self.read(), 1)
        self.assertEqual(self.rows("SELECT COUNT(DISTINCT message_id) FROM pl_usage"), [(3,)])

    def test_a_message_falls_in_the_turn_it_was_said_in_and_a_shorter_file_is_read_from_its_start(self):
        at = usage.at_of("2026-11-16T10:03:00.000Z")
        self.port.write(lambda con, rec: con.executemany(
            "INSERT INTO pl_turns (sid, n, plan_id, ticket, phase, prompt_len, started_at, ended_at) VALUES ('s1', ?, 0, '', '', 1, ?, 0)",
            [(1, at - 600000), (2, at)]))
        self.read()
        self.assertEqual(self.rows("SELECT message_id, turn FROM pl_usage WHERE token_type = 'input' ORDER BY message_id"),
                         [("msg_1", 1), ("msg_2", 2)])
        self.path.write_text(reply("msg_9", input_tokens=2) + "\n", encoding="utf-8")  # written again, shorter
        self.assertEqual(self.read(), 1)
        self.assertGreater(usage.at_of("no stamp"), at)  # a stamp that cannot be read: now

    def test_the_end_of_a_turn_reads_the_transcript_the_hook_names(self):
        event = HookIO.read(json.dumps({"hook_event_name": "Stop", "session_id": "s1", "cwd": str(self.repo),
                                        "transcript_path": str(self.path)}))
        self.assertEqual(event.input, {"stop_hook_active": False, "transcript_path": str(self.path)})
        build_runner(self.claude_dir).run(event)
        self.assertEqual(self.rows("SELECT COUNT(DISTINCT message_id) FROM pl_usage WHERE sid = 's1'"), [(2,)])
        build_runner(self.claude_dir).run(Event("Stop", "", {"stop_hook_active": False, "transcript_path": "/no/such/file"}, "s1", "/w"))
        self.assertEqual(self.rows("SELECT COUNT(DISTINCT message_id) FROM pl_usage WHERE sid = 's1'"), [(2,)])  # never blocks

    def test_backfill_reports_then_records_and_seeds_list_prices_and_the_views_give_cost(self):
        run = caller(self.claude_dir)
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.folder)}):
            self.assertEqual(usage.transcripts(), [("s1", self.path)])
            said = run("ledger", "usage_backfill").text
            self.assertIn("2 message(s) of 1 transcript(s) are not in the ledger yet", said)
            self.assertIn("s1: 2 message(s), 1000130 tokens", said)
            self.assertEqual(self.rows("SELECT COUNT(*) FROM pl_usage"), [(0,)])  # a report writes nothing
            done = run("ledger", "usage_backfill", write=True).text
            self.assertIn("2 message(s) of 1 transcript(s) recorded", done)
            self.assertIn(f"{4 * len(usage.LIST_PRICES)} list price(s) seeded", done)
            again = run("ledger", "usage_backfill", write=True).text
        self.assertIn("0 message(s) of 1 transcript(s) recorded", again)
        self.assertNotIn("seeded", again)  # a table with prices is left as it is
        self.assertEqual(self.rows("SELECT rate FROM pl_prices WHERE model_pattern = 'claude-opus-5-5' ORDER BY token_type"),
                         [(0.2,), (5.0,), (4.0,), (20.0,)])  # cache_read, cache_write (1.25 x input), input, output
        tokens, cost = self.rows("SELECT tokens, cost FROM pl_retro_session WHERE sid = 's1'")[0]
        self.assertEqual(tokens, 1000130)
        expected = (10 * 4.0 + 20 * 20.0 + 100 * 5.0 + 1000000 * 0.10) / 1000000  # tokens x list price, not a bill
        self.assertAlmostEqual(cost, expected, places=9)


    def test_with_write_the_backfill_reports_what_it_wrote(self):
        run = caller(self.claude_dir)
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.folder)}), \
                mock.patch.object(usage, "pending", return_value=(1, 15)):  # counted before the transcript grew
            done = run("ledger", "usage_backfill", write=True).text
        self.assertIn("2 message(s) of 1 transcript(s) recorded", done)
        self.assertIn("s1: 2 message(s), 1000130 tokens", done)  # what is in the ledger now
        self.assertEqual(self.rows("SELECT SUM(tokens) FROM pl_usage"), [(1000130,)])


if __name__ == "__main__":
    unittest.main()
