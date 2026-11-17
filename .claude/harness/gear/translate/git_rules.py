"""GitRuleFacts: the facts of every git command of a shell line before it runs, for the git rules (gear/rules/git.json,
when rows: spec 13 section 7). It only describes; the rows say when a rule applies. One rule action per git command the
reader saw whole (git_actions of gear/translate/git_cli.py), with the git view of the port (git_view: the branch a
repository is on, what a push would send, the home). A command whose repository has no view gives no action.

The facts (VOCABULARY), each a bool but sub:
- sub: the git subcommand;
- protected: it touches a protected branch: the repository is on one, a push names one (or --all, --mirror), a branch
  -d/-D/-f/-m names one (protected: project.json, default main and master). Every rule of git.json holds only there,
  but every fact is described on any branch, so a stricter row may hold elsewhere;
- unread_globals: a global option the gate does not follow (-c, --git-dir, --work-tree...);
- no_verify: --no-verify, or commit -n;
- add_all: git add -A / --all / . / :/ / *;
- agent_files: agent files (.claude/, CLAUDE.md, .mcp.json, AGENTS.md) staged by git add, or in the commits a push sends;
- reset_hard: git reset --hard;
- force: push --force / -f / --force-with-lease / --mirror / +refspec;
- from_home: a push from the home, the repository that holds the harness;
- protected_write: a write on a protected branch: merge, rebase, cherry-pick, revert, am, pull or reset while on one, a
  push to one (or --all, --mirror), a branch -d/-D/-f/-m of one.
details holds, for each fact that is true, the words a rule's answer shows in brackets."""
from __future__ import annotations

from typing import Any, Optional

from harness.utils.contracts import RULE_ACTIONS, Event, Translator
from harness.utils.shapes import Facts, GitFacts

AGENT_FILES = ("CLAUDE.md", "CLAUDE.local.md", ".mcp.json", "AGENTS.md")
ADD_ALL = {"-A", "--all", ".", ":/", ":/*", "*", "--no-ignore-removal"}
BRANCH_WRITES = {"merge", "rebase", "cherry-pick", "revert", "am", "pull", "reset"}
BRANCH_CHANGES = {"-d", "-D", "--delete", "-f", "--force", "-m", "-M", "--move"}
PUSH_VALUES = {"--repo", "-o", "--push-option", "--receive-pack", "--exec"}
FORCE = {"--force", "--force-with-lease", "--force-if-includes", "--mirror"}


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


class GitRuleFacts(Translator):
    """One rule action per git command of a shell line before it runs, with the facts the git rules match."""
    READS = ("git_view", "git_actions")
    VOCABULARY = ("sub", "protected", "unread_globals", "no_verify", "add_all", "agent_files", "reset_hard", "force",
                  "from_home", "protected_write")

    def translate(self, event: Event, facts: Optional[Facts] = None) -> Facts:
        """The rule actions of the git commands of a call before it runs; {} for any other call or without a view."""
        facts = facts or {}
        view = facts.get("git_view")
        if event.kind != "PreToolUse" or view is None:
            return {}
        actions = [self.facts_of(a, view) for a in facts.get("git_actions", []) if "unread" not in a]
        return {RULE_ACTIONS: actions} if actions else {}

    def facts_of(self, action: dict[str, Any], view: GitFacts) -> dict[str, Any]:
        """The facts of one git command and the details of those that are true.

        Args:
            action: one git command of the line (GitAction: sub, args, repo, globals).
            view: the port's git facts.

        Returns:
            {sub, every fact of VOCABULARY, details: {fact: words}}.
        """
        sub, args, repo = action["sub"], action["args"], action["repo"]
        out: dict[str, Any] = {"sub": sub, **{f: False for f in self.VOCABULARY[1:]}}
        details: dict[str, str] = {}
        out["details"] = details
        out["protected"] = self.touches_protected(sub, args, repo, view)  # described on every branch: rows decide

        def mark(fact: str, words: str) -> None:
            out[fact] = True
            details[fact] = f"{details[fact]}; {words}" if fact in details else words
        if action["globals"]:
            mark("unread_globals", f"git {' '.join(action['globals'])} {sub}")
        if "--no-verify" in args or (sub == "commit" and "n" in shorts(args)):
            mark("no_verify", f"git {sub} --no-verify")
        if sub == "add":
            if any(a in ADD_ALL for a in args):
                mark("add_all", f"git add {' '.join(args)}")
            agents = [a for a in args if not a.startswith("-") and agent_file(a)]
            if agents:
                mark("agent_files", f"git add {', '.join(agents)}")
        if sub == "reset" and "--hard" in args:
            mark("reset_hard", f"git reset {' '.join(args)}")
        if sub == "push":
            self.push(args, repo, view, mark)
        if sub in BRANCH_WRITES and view.protected(view.branch_of(repo)):
            mark("protected_write", f"git {sub} on {view.branch_of(repo)}")
        if sub == "branch" and set(args) & BRANCH_CHANGES and [a for a in args if not a.startswith("-") and view.protected(a)]:
            mark("protected_write", f"git branch {' '.join(args)}")
        return out

    @staticmethod
    def touches_protected(sub: str, args: list[str], repo: str, view: GitFacts) -> bool:
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

    @staticmethod
    def push(args: list[str], repo: str, view: GitFacts, mark: Any) -> None:
        """Mark the facts of one git push: force, from_home, protected_write, agent_files.

        Args:
            args: the words after git push.
            repo: the repository it runs in.
            view: the port's git facts.
            mark: mark(fact, words), which sets a fact and its detail.
        """
        options, remote, refspecs = push_parts(args)
        if set(options) & FORCE or any(o.startswith("--force-with-lease=") for o in options) or "f" in shorts(options) \
                or any(r.startswith("+") for r in refspecs):
            mark("force", f"git push {' '.join(args)}")
        if view.is_home(repo):
            mark("from_home", f"git push from {repo}")
        deleting = bool({"-d", "--delete"} & set(options))
        pairs = [("" if deleting else src, dst or src)
                 for src, _, dst in (spec.lstrip("+").partition(":") for spec in refspecs)]
        if not refspecs:
            pairs = [("HEAD", view.branch_of(repo))]
        if "--all" in options or "--mirror" in options:
            mark("protected_write", f"git push {' '.join(options)} sends every branch")
        hit = [dst for _, dst in pairs if view.protected(dst.removeprefix("refs/heads/"))]
        if hit:
            mark("protected_write", f"git push to {', '.join(hit)}")
        agents = sorted({f for src, _ in pairs if src for f in view.unpushed(repo, remote, src) if agent_file(f)})
        if agents:
            mark("agent_files", f"the push would send {', '.join(agents[:5])}")
