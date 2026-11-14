"""h9.commit-gate: a commit goes through only when the plan's verify passed and no staged file changed since, and only
with files the plan names; a commit that went through is kept and delivers the plan."""
import json
import subprocess
import unittest

import harness.gear as gear_block
from harness.assemble.engine.config import Config
from harness.utils.plan.verify import verify
from harness.assemble.engine.build import build_runner
from harness.assemble.engine.ports import LedgerPort
from harness.gear.decide.arbiter import Decide
from harness.assemble.engine.pipeline import PipelineBook
from harness.assemble.engine.ports import GitView
from harness.gear.detect.git import GitRules
from harness.gear.translate.git import GitCommands
from harness.utils.contracts import Event
from harness.utils.git.facts import staged, top
from harness.utils.git.run import GitError, git
from tests import CLAUDE_DIR, WINDOWS, native, tree
from tests.e2e import copy_tree, git_repo


def bash(command, cwd, kind="PreToolUse"):
    return Event(kind, "Bash", {"command": command}, "s1", str(cwd))


def commit_fact(command):
    return GitCommands().translate(bash(command, native("C:/r"))).get("git_commit")


class GitCommandsTest(unittest.TestCase):
    def test_a_plain_commit_is_found_with_its_repository(self):
        # several -C resolve like git does; the gate then compares that repository with the plan's
        cases = {"git commit -m x": native("C:/r"), "git -C sub commit -m 'a && b'": native("C:/r/sub"), "git commit -q -m x": native("C:/r"),
                 "git -C . -C .. commit -m x": native("C:/"), 'g""it commit -m x': native("C:/r"),  # the shell runs git itself
                 "g\\it commit -m x": native("C:/r"),  # bash reads g\it as git: it is a plain commit, judged as one
                 "git -C %X% commit -m x": native("C:/r/%X%"),  # % is no expansion in bash: a folder of that name
                 "git commit -F - <<EOF\nmessage\nEOF": native("C:/r"),  # the message from a heredoc the reader sees whole
                 "git commit --message=x": native("C:/r"), "git commit -F msg.txt": native("C:/r"), native("git -C C:/other commit"): native("C:/other")}
        for command, repo in cases.items():
            with self.subTest(command=command):
                self.assertEqual((commit_fact(command)["repo"], commit_fact(command)["unsafe"]), (repo, ""))

    def test_the_line_is_read_in_the_dialect_of_its_tool(self):
        for command in ("g\\it commit -m x", "git commit -m $msg", "& git commit -m x", "git commit -m (Get-Date)"):
            with self.subTest(command=command):
                fact = GitCommands().translate(Event("PreToolUse", "PowerShell", {"command": command}, "s1", native("C:/r")))
                self.assertTrue(fact["git_commit"]["unsafe"], command)
        self.assertTrue(commit_fact("cmd /c \"git -C %X% commit -m x\"")["unsafe"])

    def test_a_wrapped_commit_is_seen_and_named_by_its_wrapper(self):
        for command, wrapper in (("bash -c 'git commit -m x'", "bash -c"), ("sudo git commit -m x", "sudo"),
                                 ("env -i git commit -m x", "env"), ("eval git commit -m x", "eval")):
            with self.subTest(command=command):
                self.assertIn(wrapper, commit_fact(command)["unsafe"])

    def test_a_commit_the_gate_cannot_see_whole_is_unsafe(self):
        for command in ("git add x && git commit -m y", "echo a; git commit -m x", "cd other && git commit -m x",
                        "git commit -a -m x", "git commit -am x", "git commit --all -m x", "git commit a.py -m x",
                        "git commit -m x -- a.py", "git commit -i a.py -m x", "git commit -o a.py -m x",
                        "git commit --amend -m x", "FOO=1 git commit -m x", "git --git-dir=x commit -m y",
                        "git --work-tree x commit -m y", "git -c core.hooksPath=h commit -m y",
                        "bash -c 'git commit -m x'", "sh -c \"git commit -m x\"", "cmd /c git commit -m x",
                        "powershell -Command git commit -m x",
                        # what the second review found
                        "echo hi\ngit commit -a -m x", "(git commit -a)", "{ git commit -a; }",
                        "if true; then git commit -a; fi", "echo $(git commit -a)", "echo `git commit -a`",
                        "time git commit -a", "env git commit -a", "command git commit -a", "sudo git commit -a",
                        "xargs git commit -a", "eval \"git commit -a\"", "python -c \"import os; os.system('git commit -a')\"",
                        "git -c alias.ci=commit ci -a", "git ci -a -m x", "git --config-env core.hookspath=H commit",
                        "git --config-env=core.hookspath=H commit", "git commit -m \"$(git commit -a -m z)\"",
                        "git commit -m \"`git add -A`\"", "git commit --amen -m x", "git commit --no-ver -m x",
                        "git commit --al -m x", "git commit --pathspec-from-f=f", "git cherry-pick abc",
                        "git merge other", "git revert abc", "git am p.patch", "git rebase main", "git pull",
                        "git commit-tree abc -m x", "git update-ref HEAD abc",
                        # what the third review found
                        "git${IFS}commit${IFS}-m${IFS}x", "$'git' commit -m x", "{git,commit} -m x",
                        "git -C $X commit -m x", "git -C ~/o commit -m x",
                        "git-commit -m x"):
            with self.subTest(command=command):
                fact = commit_fact(command)
                self.assertTrue(fact and fact["unsafe"], command)

    def test_other_commands_are_no_commit(self):
        for command in ("git status", "gitk commit", "git log --grep commit", "bash -c 'ls'", "git add a.py",
                        "git diff --cached", "git push", "ls; git status", "pip install gitpython",
                        "git log --format=%H -1", "git show HEAD~1"):
            with self.subTest(command=command):
                self.assertIsNone(commit_fact(command))

    def test_a_commit_through_powershell_is_read_too(self):
        event = Event("PreToolUse", "PowerShell", {"command": "git add a.py; git commit -m x"}, "s1", native("C:/r"))
        self.assertTrue(GitCommands().translate(event)["git_commit"]["unsafe"])


class GitRulesTest(unittest.TestCase):
    """The git rules P1-P8 on real repositories: one remote, a branch of work and a protected main."""

    def setUp(self):
        self.repo = git_repo(self, {"a.py": "X = 1\n"})  # on branch work
        self.remote = tree(self, {})
        git(self.remote, "init", "-q", "--bare")
        git(self.repo, "remote", "add", "origin", str(self.remote))
        git(self.repo, "push", "-q", "origin", "work")
        self.view = GitView(tree(self, {}) / ".claude", ("main", "release/*"))

    def found(self, command, view=None):
        event = Event("PreToolUse", "Bash", {"command": command}, "s1", str(self.repo))
        facts = {**GitCommands().translate(event), "git_view": view or self.view}
        return sorted({f.kind for f in GitRules().detect(event, facts)})

    def test_p1_adding_everything_is_refused(self):
        for command in ("git add -A", "git add .", "git add --all", "git add :/", "git -C . add -A"):
            with self.subTest(command=command):
                self.assertEqual(self.found(command), ["git.add_all"])
        self.assertEqual(self.found("git add a.py b.py"), [])

    def test_p2_skipping_the_hooks_is_refused(self):
        for command in ("git push --no-verify origin work", "git merge --no-verify x"):
            with self.subTest(command=command):
                self.assertIn("git.no_verify", self.found(command))
        self.assertIn("git.no_verify", self.found("git commit -nm x"))
        self.assertNotIn("git.no_verify", self.found("git push -n origin work"))  # push -n is a dry run

    def test_p3_reset_hard_is_refused(self):
        self.assertEqual(self.found("git reset --hard HEAD~1"), ["git.reset_hard"])
        self.assertEqual(self.found("git reset a.py"), [])

    def test_p4_a_force_push_is_refused(self):
        for command in ("git push --force origin work", "git push -f", "git push -fu origin work",
                        "git push --force-with-lease origin work", "git push --force-with-lease=work origin work",
                        "git push origin +work"):
            with self.subTest(command=command):
                self.assertIn("git.force_push", self.found(command))
        self.assertEqual(self.found("git push origin work"), [])

    def test_p5_a_write_on_a_protected_branch_is_refused(self):
        for command in ("git push origin main", "git push origin work:main", "git push origin HEAD:refs/heads/main",
                        "git push origin release/2.1", "git push --all origin", "git push --delete origin main",
                        "git branch -D main"):
            with self.subTest(command=command):
                self.assertIn("git.protected_write", self.found(command))
        git(self.repo, "checkout", "-q", "-b", "main")
        for command in ("git push", "git merge work", "git rebase work", "git pull", "git reset HEAD~1",
                        "git cherry-pick abc"):
            with self.subTest(on="main", command=command):
                self.assertIn("git.protected_write", self.found(command))
        git(self.repo, "checkout", "-q", "work")
        for command in ("git push", "git merge main", "git push origin work", "git branch -d old"):
            with self.subTest(on="work", command=command):
                self.assertNotIn("git.protected_write", self.found(command))

    def test_p6_the_home_never_pushes(self):
        home = GitView(self.repo / ".claude", ("main",))
        self.assertIn("push.never_repo", self.found("git push origin work", home))
        self.assertNotIn("push.never_repo", self.found("git push origin work"))

    def test_p7_agent_files_never_reach_a_remote(self):
        for command in ("git add .claude/settings.json", "git add CLAUDE.md", "git add sub/.mcp.json"):
            with self.subTest(command=command):
                self.assertEqual(self.found(command), ["push.agent_files"])
        self.assertEqual(self.found("git push origin work"), [])
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "notes.md").write_text("x", encoding="utf-8")
        git(self.repo, "add", ".claude/notes.md")
        git(self.repo, "commit", "-q", "-m", "agent file")
        for command in ("git push origin work", "git push", "git push origin HEAD:other"):
            with self.subTest(command=command):
                self.assertIn("push.agent_files", self.found(command))

    def test_p8_a_global_option_the_gate_does_not_follow_is_asked(self):
        for command in ("git -c core.hooksPath=/dev/null push origin work", "git --git-dir=/x/.git status",
                        "git --work-tree=/x add a.py"):
            with self.subTest(command=command):
                self.assertIn("git.unread", self.found(command))
        self.assertEqual(self.found("git -C . status"), [])

    def test_the_rules_say_why_and_the_floor_runs_them(self):
        rules = Decide.load(CLAUDE_DIR).rules
        for kind in ("git.add_all", "git.no_verify", "git.reset_hard", "git.force_push", "git.protected_write",
                     "push.never_repo", "push.agent_files"):
            with self.subTest(kind=kind):
                self.assertEqual(rules[kind]["verdict"], "refuse")
        self.assertEqual(rules["git.unread"]["verdict"], "ask")
        self.assertIn("git_rules", PipelineBook(CLAUDE_DIR / "harness" / "assemble" / "pipelines").resolve("base").detectors)

    def test_only_a_call_before_it_runs_is_judged(self):
        event = Event("PostToolUse", "Bash", {"command": "git push --force"}, "s1", str(self.repo))
        self.assertEqual(GitRules().detect(event, {**GitCommands().translate(event), "git_view": self.view}), [])


if __name__ == "__main__":
    unittest.main()
