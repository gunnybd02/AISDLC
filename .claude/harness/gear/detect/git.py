"""GitRules: the findings of every git command of a shell line before it runs (gear/translate/git_cli.py), against the
git rules of docs/architecture.md (gear/rules/git.json). They hold only where a protected branch is touched: the
repository is on one, a push names one (or --all, --mirror), a branch -d/-D/-f/-m names one. Elsewhere git is free.
Each one asks the user, never refuses: the git block (run('git', 'run')) keeps the user's word in SQL.
- git.add_all: git add -A / --all / . / :/ / * - stage the files by name;
- git.no_verify: --no-verify, or commit -n - the repository's own hooks are never skipped;
- git.reset_hard: git reset --hard - uncommitted work is never thrown away;
- git.force_push: push --force / -f / --force-with-lease / --mirror / +refspec - history on a remote is never rewritten;
- git.protected_write: a write on a protected branch: merge, rebase, cherry-pick, revert, am, pull or reset while on
  one, a push to one (or --all), a branch -d/-D/-f/-m of one (protected: project.json, default main and master);
- push.never_repo: a push from the home, the repository that holds the harness;
- push.agent_files: agent files (.claude/, CLAUDE.md, .mcp.json, AGENTS.md) staged by git add, or in the commits a
  push would send;
- git.unread: git given a global option the gate does not follow (-c, --git-dir, --work-tree...), which may move it
  to another repository or skip its hooks.
The git facts it needs come from the port's git_view (the branch a repository is on, what a push would send, the
home), read only when a command needs them."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol

from harness.utils.contracts import Detector, Event, Finding
from harness.utils.shapes import Facts

if TYPE_CHECKING:
    from harness.gear.translate.git_cli import GitAction

AGENT_FILES = ("CLAUDE.md", "CLAUDE.local.md", ".mcp.json", "AGENTS.md")
ADD_ALL = {"-A", "--all", ".", ":/", ":/*", "*", "--no-ignore-removal"}
BRANCH_WRITES = {"merge", "rebase", "cherry-pick", "revert", "am", "pull", "reset"}
BRANCH_CHANGES = {"-d", "-D", "--delete", "-f", "--force", "-m", "-M", "--move"}
PUSH_VALUES = {"--repo", "-o", "--push-option", "--receive-pack", "--exec"}
FORCE = {"--force", "--force-with-lease", "--force-if-includes", "--mirror"}


class GitView(Protocol):
    """The git facts of the port (the fact git_view; assemble/engine/ports.py GitView), each read only when called."""

    def branch_of(self, repo: str) -> str:
        """The branch the repository is on ("" when it is not a folder)."""
        ...

    def protected(self, branch: str) -> bool:
        """Whether the branch is protected (project.json protected, default main and master)."""
        ...

    def unpushed(self, repo: str, remote: str, source: str) -> list[str]:
        """The files of the commits a push of source to remote would send."""
        ...

    def is_home(self, repo: str) -> bool:
        """Whether repo is the repository that holds the harness."""
        ...


def agent_file(path: str) -> bool:
    """Whether a path is an agent file: under a .claude folder, a .claude folder, or CLAUDE.md, CLAUDE.local.md,
    .mcp.json or AGENTS.md.

    Args:
        path: a path as git or a commit names it (either slash).

    Returns:
        True for an agent file.
    """
    parts = path.replace("\\", "/").strip("/").split("/")
    return ".claude" in parts[:-1] or parts[-1] in AGENT_FILES or path.replace("\\", "/").rstrip("/").endswith(".claude")


def shorts(args: list[str]) -> set[str]:
    """The letters of the short options among args (-fu is f and u).

    Args:
        args: the words of a git command after its subcommand.

    Returns:
        The set of letters, e.g. {"f", "u"}.
    """
    return {c for a in args if a.startswith("-") and not a.startswith("--") for c in a[1:]}


def push_parts(args: list[str]) -> tuple[list[str], str, list[str]]:
    """(options, remote, refspecs) of the words after git push.

    Args:
        args: the words after git push.

    Returns:
        (the options in order, the remote ("origin" when none is named), the refspecs after it).
    """
    options, positional, i = [], [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            positional += args[i + 1:]
            break
        if a.startswith("-"):
            options.append(a)
            i += 2 if a in PUSH_VALUES else 1
            continue
        positional.append(a)
        i += 1
    return options, (positional[0] if positional else "origin"), positional[1:]


class GitRules(Detector):
    """The git rules, where a protected branch is touched: git.add_all, git.no_verify, git.reset_hard, git.force_push,
    git.protected_write, push.never_repo, push.agent_files, git.unread."""

    def detect(self, event: Event, facts: Facts) -> list[Finding]:
        """Report the git rules' findings for each git command of a shell line before it runs (git_actions), the
        ones the reader saw whole."""
        if event.kind != "PreToolUse":
            return []
        view = facts.get("git_view")
        out = []
        for action in facts.get("git_actions", []):
            if "unread" not in action:  # a line the reader cannot see whole is refused as commit.raw already
                out += self.check(action, view)
        return out

    def check(self, action: GitAction, view: Optional[GitView]) -> list[Finding]:
        """The findings of one git command; none unless it touches a protected branch.

        Args:
            action: one git command of the line (GitAction: sub, args, repo, globals).
            view: the port's git facts, or None when there are none (then nothing is found).

        Returns:
            Its findings: git.unread, git.no_verify, git.add_all, push.agent_files, git.reset_hard, the push's
            findings and git.protected_write.
        """
        sub, args, repo = action["sub"], action["args"], action["repo"]
        if view is None or not self.touches_protected(sub, args, repo, view):
            return []
        out = []
        if action["globals"]:
            out.append(Finding("git.unread", f"git {' '.join(action['globals'])} {sub}"))
        if "--no-verify" in args or (sub == "commit" and "n" in shorts(args)):
            out.append(Finding("git.no_verify", f"git {sub} --no-verify"))
        if sub == "add":
            if any(a in ADD_ALL for a in args):
                out.append(Finding("git.add_all", f"git add {' '.join(args)}"))
            agents = [a for a in args if not a.startswith("-") and agent_file(a)]
            if agents:
                out.append(Finding("push.agent_files", f"git add {', '.join(agents)}"))
        if sub == "reset" and "--hard" in args:
            out.append(Finding("git.reset_hard", f"git reset {' '.join(args)}"))
        if sub == "push":
            out += self.push(args, repo, view)
        if view and sub in BRANCH_WRITES and view.protected(view.branch_of(repo)):
            out.append(Finding("git.protected_write", f"git {sub} on {view.branch_of(repo)}"))
        if view and sub == "branch" and set(args) & BRANCH_CHANGES:
            named = [a for a in args if not a.startswith("-") and view.protected(a)]
            if named:
                out.append(Finding("git.protected_write", f"git branch {' '.join(args)}"))
        return out

    @staticmethod
    def touches_protected(sub: str, args: list[str], repo: str, view: GitView) -> bool:
        """Whether a git command touches a protected branch: the repository is on one, a push names one (or --all,
        --mirror), or a branch command names one.

        Args:
            sub: the git subcommand.
            args: the words after it.
            repo: the repository it runs in.
            view: the port's git facts.

        Returns:
            True when the git rules hold for it.
        """
        if view.protected(view.branch_of(repo)):
            return True
        if sub == "push":
            options, _, refspecs = push_parts(args)
            dsts = [s.lstrip("+").partition(":")[2] or s.lstrip("+") for s in refspecs]
            return bool({"--all", "--mirror"} & set(options)) or any(view.protected(d.removeprefix("refs/heads/"))
                                                                    for d in dsts)
        return sub == "branch" and any(not a.startswith("-") and view.protected(a) for a in args)

    def push(self, args: list[str], repo: str, view: Optional[GitView]) -> list[Finding]:
        """The findings of one git push.

        Args:
            args: the words after git push.
            repo: the repository it runs in.
            view: the port's git facts, or None (then only a force push is found).

        Returns:
            git.force_push, push.never_repo (a push from the home), git.protected_write (--all, --mirror or a
            protected destination) and push.agent_files (agent files in the commits it would send).
        """
        options, remote, refspecs = push_parts(args)
        out = []
        if set(options) & FORCE or any(o.startswith("--force-with-lease=") for o in options) or "f" in shorts(options) \
                or any(r.startswith("+") for r in refspecs):
            out.append(Finding("git.force_push", f"git push {' '.join(args)}"))
        if view is None:
            return out
        if view.is_home(repo):
            out.append(Finding("push.never_repo", f"git push from {repo}"))
        deleting = bool({"-d", "--delete"} & set(options))
        pairs = []
        for spec in refspecs:
            src, _, dst = spec.lstrip("+").partition(":")
            pairs.append(("" if deleting else src, dst or src))
        if not refspecs:
            pairs = [("HEAD", view.branch_of(repo))]
        if "--all" in options or "--mirror" in options:
            out.append(Finding("git.protected_write", f"git push {' '.join(options)} sends every branch"))
        hit = [dst for _, dst in pairs if view.protected(dst.removeprefix("refs/heads/"))]
        if hit:
            out.append(Finding("git.protected_write", f"git push to {', '.join(hit)}"))
        agents = sorted({f for src, _ in pairs if src for f in view.unpushed(repo, remote, src) if agent_file(f)})
        if agents:
            out.append(Finding("push.agent_files", f"the push would send {', '.join(agents[:5])}"))
        return out
