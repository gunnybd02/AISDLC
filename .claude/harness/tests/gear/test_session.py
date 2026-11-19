"""The model gate: a create_session call of any server opens on Sonnet; with no model, or on another model without the
user's Allow for exactly that call, it is refused (utils/forge/sessions.py, gear/translate/session.py)."""
import unittest

from harness.assemble.engine.build import build_runner
from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.assemble.engine.wire_mcp import items_of
from harness.gear.decide.arbiter import Decide
from harness.gear.translate.session import SessionCalls
from harness.utils.contracts import Event, Verdict
from harness.utils.forge import sessions
from harness.tests import CLAUDE_DIR
from harness.tests.e2e import copy_tree, git_repo

JUDGE = Decide.load(CLAUDE_DIR)
CALL = {"title": "Orchestra p31: hello", "prompt": "the brief", "model": "claude-opus-5-5", "tags": ["orchestra"]}
TOOLS = ("mcp__claude-code-remote__create_session", "mcp__caaed075-fab9-4852-ba97-a638e8eac9e4__create_session")


def found(tool, given, held=()):
    """The findings of the real when rows for a call: SessionCalls with the passes held, then the matcher."""
    facts = {"session_pass": lambda code: code in held}
    actions = SessionCalls().translate(Event("PreToolUse", tool, given, "s1"), facts).get("rule_actions", [])
    return [(f.kind, f.detail) for f in JUDGE.matched(actions)]


class SessionGateTest(unittest.TestCase):
    def test_a_sonnet_call_runs_with_no_form(self):
        """s1.session.sonnet-free: any server's create_session on the default model; other tools are free."""
        for tool in TOOLS:
            with self.subTest(tool=tool):
                self.assertEqual(found(tool, {**CALL, "model": "claude-sonnet-5-5"}), [])
                self.assertEqual(found(tool, {**CALL, "model": " Claude-Sonnet-5-5 "}), [])
        self.assertEqual(sessions.DEFAULT_MODEL, "claude-sonnet-5-5")
        self.assertEqual(found("mcp__claude-code-remote__get_session", CALL), [])
        self.assertEqual(found("create_session", CALL), [])  # not an MCP tool
        self.assertEqual(SessionCalls().translate(Event("PostToolUse", TOOLS[0], CALL, "s1"), {}), {})

    def test_a_call_with_no_model_is_refused(self):
        """s1.session.no-model: no model, or an empty one, is refused and names the default."""
        for given in ({k: v for k, v in CALL.items() if k != "model"}, {**CALL, "model": ""}, {**CALL, "model": None}):
            with self.subTest(given=given):
                self.assertEqual(found(TOOLS[0], given), [("session.no_model", "claude-sonnet-5-5")])
        self.assertEqual(JUDGE.codes["session.no_model"]["verdict"], "refuse")

    def test_another_model_is_refused_with_the_form_question(self):
        """s1.session.no-pass: the exact question; a pass for another model, title or prompt does not open it."""
        q = sessions.question(CALL)
        self.assertEqual(q, f'Open a session on claude-opus-5-5: "Orchestra p31: hello" [{sessions.call_code(CALL)}]?')
        self.assertRegex(q, sessions.ASKED)
        for tool in TOOLS:
            with self.subTest(tool=tool):
                self.assertEqual(found(tool, CALL), [("session.no_pass", q)])
        code = sessions.call_code(CALL)
        self.assertEqual(found(TOOLS[0], CALL, held={code}), [])
        for other in ({**CALL, "model": "claude-fable-5-2"}, {**CALL, "title": "x"}, {**CALL, "prompt": "another"}):
            with self.subTest(other=other):
                self.assertEqual(found(TOOLS[0], other, held={code})[0][0], "session.no_pass")
        self.assertEqual(JUDGE.codes["session.no_pass"]["verdict"], "refuse")
        odd = {**CALL, "title": 'a "quoted"\n title'}
        self.assertIn('"a \'quoted\' title"', sessions.question(odd))  # one line, no double quote inside
        self.assertRegex(sessions.question(odd), sessions.ASKED)


class SessionGateFlowTest(unittest.TestCase):
    """The hook's whole pipeline: refused, the user's Allow, then the call runs once."""

    def setUp(self):
        self.claude_dir = copy_tree(self)
        self.repo = git_repo(self, {"a.py": "X = 1\n"})
        self.port = LedgerPort(self.claude_dir)
        self.port.touch_session("s1")
        self.runner = build_runner(self.claude_dir, items_of(self.claude_dir))

    def judge(self, given=None):
        verdict = self.runner.run(Event("PreToolUse", TOOLS[0], given or CALL, "s1", str(self.repo))).verdict
        return verdict.decision, verdict.reason

    def answer(self, q, label):
        return Act(self.port).run(Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": q}]}, "s1",
                                        str(self.repo)), {"answers": {q: label}}, Verdict("allow"))

    def opened(self, response):
        Act(self.port).run(Event("PostToolUse", TOOLS[0], CALL, "s1", str(self.repo), response), {}, Verdict("allow"))

    def test_the_form_answer_opens_one_session(self):
        """s1.session.allow-once through the hook: refuse, Deny, refuse, Allow, run, a failed call keeps the pass, an
        opened session uses it, refuse again."""
        q = sessions.question(CALL)
        decision, why = self.judge()
        self.assertEqual(decision, "refuse")
        self.assertIn(f"({q})", why)
        self.assertEqual(self.judge({**CALL, "model": "claude-sonnet-5-5"})[0], "allow")
        self.answer(q, "Deny")
        self.assertEqual(self.judge()[0], "refuse")
        notes = self.answer(q + "\nOne child needs the bigger model.", "Allow")
        self.assertTrue(any(n.startswith(f"GATE: the user allows the session [{sessions.call_code(CALL)}]")
                            for n in notes))
        self.assertEqual(self.judge()[0], "allow")
        self.opened({"error": "the environment is not reachable"})
        self.assertEqual(self.judge()[0], "allow")  # nothing opened: the pass stays
        self.opened('{"session_id": "session_01EXL6xVaMi4LMQbwg257rUu", "status": "running"}')
        self.assertEqual(self.judge()[0], "refuse")  # one Allow is one session


if __name__ == "__main__":
    unittest.main()
