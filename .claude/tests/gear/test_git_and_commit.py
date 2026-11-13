"""h9.commit-gate: a commit goes through only when the plan's verify passed and no staged file changed since, and only
with files the plan names; a commit that went through is kept and delivers the plan."""
import json
import subprocess
import unittest

import harness.gear as gear_block
from harness.assemble.blocks import verify
from harness.assemble.build import build_runner
from harness.assemble.ports import LedgerPort
from harness.gear.decide.arbiter import Decide
from harness.gear.detect.commit import CommitGate
from harness.gear.translate.git import GitCommands
from harness.utils.contracts import Event
from harness.utils.git.facts import staged, top
from harness.utils.git.run import GitError, git
from tests import CLAUDE_DIR, tree
from tests.e2e import copy_tree, git_repo


def bash(command, cwd, kind="PreToolUse"):
    return Event(kind, "Bash", {"command": command}, "s1", str(cwd))


def commit_fact(command):
    return GitCommands().translate(bash(command, "C:/r")).get("git_commit")


class GitCommandsTest(unittest.TestCase):
    def test_a_plain_commit_is_found_with_its_repository(self):
        # several -C resolve like git does; the gate then compares that repository with the plan's
        cases = {"git commit -m x": "C:/r", "git -C sub commit -m 'a && b'": "C:/r/sub", "git commit -q -m x": "C:/r",
                 "git -C . -C .. commit -m x": "C:/", 'g""it commit -m x': "C:/r",  # the shell runs git itself
                 "g\\it commit -m x": "C:/r",  # bash reads g\it as git: it is a plain commit, judged as one
                 "git -C %X% commit -m x": "C:/r/%X%",  # % is no expansion in bash: a folder of that name
                 "git commit -F - <<EOF\nmessage\nEOF": "C:/r",  # the message from a heredoc the reader sees whole
                 "git commit --message=x": "C:/r", "git commit -F msg.txt": "C:/r", "git -C C:/other commit": "C:/other"}
        for command, repo in cases.items():
            with self.subTest(command=command):
                self.assertEqual((commit_fact(command)["repo"], commit_fact(command)["unsafe"]), (repo, ""))

    def test_the_line_is_read_in_the_dialect_of_its_tool(self):
        for command in ("g\\it commit -m x", "git commit -m $msg", "& git commit -m x", "git commit -m (Get-Date)"):
            with self.subTest(command=command):
                fact = GitCommands().translate(Event("PreToolUse", "PowerShell", {"command": command}, "s1", "C:/r"))
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
        event = Event("PreToolUse", "PowerShell", {"command": "git add a.py; git commit -m x"}, "s1", "C:/r")
        self.assertTrue(GitCommands().translate(event)["git_commit"]["unsafe"])


class GitRunTest(unittest.TestCase):
    def test_git_runs_from_a_list_and_reads_the_staged_files(self):
        repo = git_repo(self, {"a.py": "x\n"})
        (repo / "a.py").write_text("y\n", encoding="utf-8")
        git(repo, "add", "a.py")
        self.assertEqual(top(repo / "a.py").lower(), str(repo).replace("\\", "/").lower())
        self.assertEqual(list(staged(repo)), ["a.py"])
        with self.assertRaises(GitError):
            git(repo, "no-such-command")

    def test_a_rename_shows_the_file_it_takes_away(self):
        repo = git_repo(self, {"secret.txt": "s\n"})
        git(repo, "mv", "secret.txt", "b.py")
        self.assertEqual(sorted(staged(repo)), ["b.py", "secret.txt"])
        self.assertIsNone(staged(repo)["secret.txt"])


PLAN = {"id": 7, "plan_id": "pd-1", "rev": 1, "root": "C:/r", "title": "t", "files": ["a.py"], "tests": ["test_a.py"]}


def kinds(commit, plan=PLAN, unsafe=""):
    facts = {"plan": plan, "git_commit": {"repo": "C:/r", "unsafe": unsafe}, "commit_view": lambda repo, plan_row: commit}
    return [f.kind for f in CommitGate().detect(bash("git commit", "C:/r"), facts)]


class CommitGateTest(unittest.TestCase):
    def commit(self, receipt, staged_files, repo="C:/r"):
        return {"repo": repo, "plan_repo": "C:/r", "staged": staged_files, "receipt": receipt}

    def test_an_unsafe_commit_is_refused_before_anything_else(self):
        self.assertEqual(kinds(self.commit({"ok": 1, "files": {}}, {}), unsafe="compound"), ["commit.unsafe"])
        self.assertEqual(kinds(None, plan=None, unsafe="compound"), ["commit.unsafe"])

    def test_a_commit_in_another_repository_than_the_plans_is_refused(self):
        self.assertEqual(kinds(self.commit({"ok": 1, "files": {"a.py": "h1"}}, {"a.py": "h1"}, repo="C:/other")),
                         ["commit.outside"])

    def test_a_commit_without_a_passing_verify_is_refused(self):
        self.assertEqual(kinds(self.commit(None, {"a.py": "h1"})), ["commit.unverified"])
        self.assertEqual(kinds(self.commit({"ok": 0, "files": {"a.py": "h1"}}, {"a.py": "h1"})), ["commit.unverified"])

    def test_a_file_changed_after_the_verify_is_refused(self):
        self.assertEqual(kinds(self.commit({"ok": 1, "files": {"a.py": "h1"}}, {"a.py": "h2"})), ["commit.changed"])

    def test_a_staged_file_outside_the_plan_is_refused(self):
        found = kinds(self.commit({"ok": 1, "files": {"a.py": "h1"}}, {"a.py": "h1", "b.py": "h9"}))
        self.assertEqual(found, ["commit.outside"])

    def test_a_commit_without_a_plan_is_refused(self):
        self.assertEqual(kinds(self.commit(None, {"a.py": "h1"}), plan=None), ["plan.none"])

    def test_a_verified_commit_of_plan_files_passes(self):
        self.assertEqual(kinds(self.commit({"ok": 1, "files": {"a.py": "h1"}}, {"a.py": "h1"})), [])

    def test_the_rules_refuse_each_finding_and_the_recipe_runs_the_gate(self):
        rules = Decide.load(CLAUDE_DIR).rules
        for kind in ("commit.unverified", "commit.changed", "commit.outside", "commit.unsafe"):
            self.assertEqual(rules[kind]["verdict"], "refuse")
        names = {i["name"] for i in gear_block.ITEMS}
        self.assertLessEqual({"git_commands", "commit_gate"}, names)


class CommitFlowTest(unittest.TestCase):
    """Through the runner with a real repository: refused before verify, allowed after, delivered once committed."""

    def setUp(self):
        self.claude_dir = copy_tree(self, {"project.json": json.dumps(
            {"name": "t", "recipe": "base", "verify": ["{python}", "-m", "unittest", "discover", "-s", "."]})})
        self.repo = git_repo(self, {"a.py": "X = 1\n", "test_a.py": "import unittest\n\nclass T(unittest.TestCase):\n"
                                                                   "    def test_x(self):\n        pass\n"})
        self.port, self.runner = LedgerPort(self.claude_dir), build_runner(self.claude_dir)
        self.plan_id, _, q = self.port.present({"title": "t", "files": ["a.py"], "tests": ["test_a.py"],
                                                "root": str(self.repo)})
        self.runner.run(Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": q}],
                                                                 "answers": {q: "Duyệt"}}, "s1", str(self.repo)))

    def test_a_commit_that_did_not_come_from_the_approval_point_delivers_nothing(self):
        verify(self.port, self.claude_dir, self.plan_id)
        git(self.repo, "commit", "--allow-empty", "-q", "-m", "unseen one")
        git(self.repo, "commit", "--allow-empty", "-q", "-m", "unseen two")
        notes = self.runner.run(bash("git commit -m x", self.repo, "PostToolUse")).notes
        self.assertIn("not made right on the commit of the approval", " ".join(notes))
        self.assertIsNotNone(self.port.approved("s1"))

    def test_a_commit_that_holds_more_than_the_verified_plan_delivers_nothing(self):
        verify(self.port, self.claude_dir, self.plan_id)
        (self.repo / "z.py").write_text("unvetted\n", encoding="utf-8")
        git(self.repo, "add", "z.py")
        git(self.repo, "commit", "-q", "-m", "made around the gate")  # parent is the base, as the gate's would be
        notes = self.runner.run(bash("git commit -m x", self.repo, "PostToolUse")).notes
        self.assertIn("not delivered", " ".join(notes))
        self.assertIsNotNone(self.port.approved("s1"))

    def test_a_commit_of_other_content_than_the_verify_saw_delivers_nothing(self):
        (self.repo / "a.py").write_text("X = 2\n", encoding="utf-8")
        verify(self.port, self.claude_dir, self.plan_id)
        (self.repo / "a.py").write_text("X = 3\n", encoding="utf-8")
        git(self.repo, "add", "a.py")
        git(self.repo, "commit", "-q", "-m", "changed after the verify")
        self.runner.run(bash("git commit -m x", self.repo, "PostToolUse"))
        self.assertIsNotNone(self.port.approved("s1"))

    def test_a_commit_that_only_changes_a_mode_delivers_nothing(self):
        verify(self.port, self.claude_dir, self.plan_id)
        git(self.repo, "update-index", "--chmod=+x", "a.py")
        git(self.repo, "commit", "-q", "-m", "mode only")
        notes = self.runner.run(bash("git commit -m x", self.repo, "PostToolUse")).notes
        self.assertIn("not delivered", " ".join(notes))
        self.assertIsNotNone(self.port.approved("s1"))

    def test_an_empty_commit_delivers_nothing(self):
        verify(self.port, self.claude_dir, self.plan_id)
        git(self.repo, "commit", "--allow-empty", "-q", "-m", "nothing")
        notes = self.runner.run(bash("git commit -m x", self.repo, "PostToolUse")).notes
        self.assertIn("changes nothing", " ".join(notes))
        self.assertIsNotNone(self.port.approved("s1"))

    def test_a_repository_without_a_commit_at_the_approval_delivers_nothing_and_breaks_nothing(self):
        empty = tree(self, {"a.py": "X = 1\n"})
        git(empty, "init", "-q", "-b", "work")
        git(empty, "config", "user.name", "t")
        git(empty, "config", "user.email", "t@t")
        plan_id, _, q = self.port.present({"title": "first", "files": ["a.py"], "tests": [], "root": str(empty)})
        self.runner.run(Event("PostToolUse", "AskUserQuestion", {"questions": [{"question": q}],
                                                                 "answers": {q: "Duyệt"}}, "s2", str(empty)))
        git(empty, "add", "a.py")
        git(empty, "commit", "-q", "-m", "root")
        event = Event("PostToolUse", "Bash", {"command": "git commit -m root"}, "s2", str(empty))
        notes = self.runner.run(event).notes
        self.assertIn("no commit", " ".join(notes))
        self.assertIsNotNone(self.port.approved("s2"))

    def test_a_path_that_differs_only_in_case_is_not_the_plan_file(self):
        verify(self.port, self.claude_dir, self.plan_id)
        git(self.repo, "mv", "a.py", "A.py")
        git(self.repo, "commit", "-q", "-m", "case")
        self.runner.run(bash("git commit -m x", self.repo, "PostToolUse"))
        self.assertIsNotNone(self.port.approved("s1"))

    def test_a_commit_in_a_folder_that_does_not_exist_is_refused(self):
        verify(self.port, self.claude_dir, self.plan_id)
        self.assertEqual(self.runner.run(bash("git -C nothere commit -m x", self.repo)).verdict.decision, "refuse")

    def test_a_commit_in_another_repository_delivers_nothing(self):
        other = git_repo(self, {"z.py": ""})
        verify(self.port, self.claude_dir, self.plan_id)
        git(other, "commit", "--allow-empty", "-q", "-m", "elsewhere")
        notes = self.runner.run(bash(f"git -C {other} commit --allow-empty -m elsewhere", self.repo, "PostToolUse")).notes
        self.assertEqual(notes, ())
        self.assertIsNotNone(self.port.approved("s1"))

    def test_verify_then_commit_delivers_the_plan(self):
        claude_dir, repo, port, runner, plan_id = self.claude_dir, self.repo, self.port, self.runner, self.plan_id
        (repo / "a.py").write_text("X = 2\n", encoding="utf-8")
        git(repo, "add", "a.py")
        commit = bash("git commit -m change", repo)
        self.assertEqual(runner.run(commit).verdict.decision, "refuse")
        self.assertIn("passed", verify(port, claude_dir, plan_id))
        self.assertEqual(runner.run(commit).verdict.decision, "allow")
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "change"], check=True)
        notes = runner.run(bash("git commit -m change", repo, "PostToolUse")).notes
        self.assertIn("delivered", " ".join(notes))
        self.assertIsNone(port.approved("s1"))
        row = port.ledger.one("SELECT commit_sha FROM rec_commits")
        self.assertEqual(row["commit_sha"], git(repo, "rev-parse", "HEAD").strip())


if __name__ == "__main__":
    unittest.main()
