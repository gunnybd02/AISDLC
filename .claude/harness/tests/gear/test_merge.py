"""The merge gate: a merge tool call of any server is refused until the user allowed exactly that pull request and head
commit in the form (utils/forge/merges.py, gear/translate/merge.py); the refusal gives the form question."""
import unittest

from harness.assemble.engine.build import build_runner
from harness.assemble.engine.ports import LedgerPort
from harness.assemble.engine.runner import Act
from harness.assemble.engine.wire_mcp import items_of
from harness.gear.decide.arbiter import Decide
from harness.gear.translate.merge import MergeCalls
from harness.utils.contracts import Event, Verdict
from harness.utils.forge import merges
from harness.tests import CLAUDE_DIR
from harness.tests.e2e import copy_tree, git_repo

JUDGE = Decide.load(CLAUDE_DIR)
SHA = "e470516a6e49def66a3f0b0b05a279e81f6d9eec"
CALL = {"owner": "gunnybd02", "repo": "AISDLC", "pullNumber": 76, "expectedHeadSha": SHA}
TOOLS = ("mcp__github__merge_pull_request", "mcp__caaed075-fab9-4852-ba97-a638e8eac9e4__merge_pull_request")


def found(tool, given, held=()):
    """The findings of the real when rows for a call: MergeCalls with the passes held, then the matcher."""
    facts = {"merge_pass": lambda code: code in held}
    actions = MergeCalls().translate(Event("PreToolUse", tool, given, "s1"), facts).get("rule_actions", [])
    return [(f.kind, f.detail) for f in JUDGE.matched(actions)]


class MergeGateTest(unittest.TestCase):
    def test_a_merge_with_no_pass_is_refused_with_the_form_question(self):
        """s2.merge.no-pass: any server's merge tool; the refusal holds the exact question."""
        q = merges.question("gunnybd02", "AISDLC", 76, SHA)
        for tool in TOOLS:
            with self.subTest(tool=tool):
                self.assertEqual(found(tool, CALL), [("merge.no_pass", q)])
        self.assertEqual(JUDGE.codes["merge.no_pass"]["verdict"], "refuse")
        self.assertEqual(found("mcp__github__get_pull_request", CALL), [])  # other tools are free
        self.assertEqual(MergeCalls().translate(Event("PostToolUse", TOOLS[0], CALL, "s1"), {}), {})

    def test_with_the_pass_the_merge_runs_and_only_that_one(self):
        """s2.merge.with-pass: the pass of this PR at this head lets it through; another PR or head does not."""
        code = merges.code_of("gunnybd02", "AISDLC", 76, SHA)
        self.assertEqual(found(TOOLS[0], CALL, held={code}), [])
        self.assertEqual(found(TOOLS[0], {**CALL, "pullNumber": 77}, held={code})[0][0], "merge.no_pass")
        self.assertEqual(found(TOOLS[0], {**CALL, "expectedHeadSha": "f" * 40}, held={code})[0][0], "merge.no_pass")
        self.assertEqual(found(TOOLS[0], {**CALL, "owner": "GunnyBD02"}, held={code}), [])  # GitHub names ignore case

    def test_a_merge_with_no_head_sha_is_refused(self):
        """s2.merge.no-head: no expectedHeadSha, or a short one, is refused and told to name it."""
        for given in ({k: v for k, v in CALL.items() if k != "expectedHeadSha"}, {**CALL, "expectedHeadSha": SHA[:12]}):
            with self.subTest(given=given):
                self.assertEqual(found(TOOLS[0], given), [("merge.no_head", "PR #76 of gunnybd02/AISDLC")])
        self.assertEqual(found(TOOLS[0], {"owner": "o"}), [("merge.no_head", "the pull request")])
        self.assertEqual(JUDGE.codes["merge.no_head"]["verdict"], "refuse")

    def test_a_shell_merge_with_gh_is_refused(self):
        """s3.merge.shell: gh pr merge and gh api on a pulls/<n>/merge path; other gh calls are free."""
        for command in ("gh pr merge 76 --merge", "cd x && gh pr merge --squash", "gh api -X PUT repos/o/r/pulls/76/merge",
                        "gh  api repos/o/r/pulls/76/merge -f merge_method=squash"):
            with self.subTest(command=command):
                hits = found("Bash", {"command": command})
                self.assertEqual([k for k, _ in hits], ["merge.shell"])
                self.assertTrue(hits[0][1].startswith("gh"))
        for command in ("gh pr view 76", "gh api repos/o/r/pulls/76", "gh api repos/o/r/pulls/76/files",
                        "echo merge", "gh pr list --search merge"):
            with self.subTest(command=command):
                self.assertEqual(found("Bash", {"command": command}), [])
        self.assertEqual(found("PowerShell", {"command": "gh pr merge 76"})[0][0], "merge.shell")
        self.assertEqual(JUDGE.codes["merge.shell"]["verdict"], "refuse")


class MergeGateFlowTest(unittest.TestCase):
    """The hook's whole pipeline: refused, the user's Allow, then the merge runs once."""

    def setUp(self):
        self.claude_dir = copy_tree(self)
        self.repo = git_repo(self, {"a.py": "X = 1\n"})
        self.port = LedgerPort(self.claude_dir)
        self.port.touch_session("s1")
        self.runner = build_runner(self.claude_dir, items_of(self.claude_dir))

    def judge(self):
        verdict = self.runner.run(Event("PreToolUse", TOOLS[0], CALL, "s1", str(self.repo))).verdict
        return verdict.decision, verdict.reason

    def test_the_form_answer_opens_one_merge(self):
        """s2.merge.no-pass and s2.merge.with-pass through the hook: refuse, Allow, run, refuse again."""
        q = merges.question("gunnybd02", "AISDLC", 76, SHA)
        decision, why = self.judge()
        self.assertEqual(decision, "refuse")
        self.assertIn(f"({q})", why)
        Act(self.port).run(Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": q}]}, "s1",
                                 str(self.repo)), {"answers": {q: "Allow"}}, Verdict("allow"))
        self.assertEqual(self.judge()[0], "allow")
        Act(self.port).run(Event("PostToolUse", TOOLS[0], CALL, "s1", str(self.repo), {"merged": True}), {},
                           Verdict("allow"))
        self.assertEqual(self.judge()[0], "refuse")  # one Allow is one merge


if __name__ == "__main__":
    unittest.main()
