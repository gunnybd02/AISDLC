"""GitCommands: whether a shell line commits, in which repository, and whether the gate can see the whole commit. The
line is read by the shell reader (utils/shell/), as its shell reads it, wrappers taken off; what it cannot see whole is
unsafe.

A commit is safe only as one plain command alone on its line:
    git [-C <dir>]... commit [-m <msg> | -F <file> | -q | -s | -v | --allow-empty | --message=.. | --file=..]...
Everything else that can make a commit is unsafe ({"unsafe": why}):
- a line holding git (quotes and backslashes taken out, so g""it counts) that the reader cannot see whole: $( ),
  backticks, a group or a subshell, a quote left open...;
- a first word that is git spelled another way (g\\it in PowerShell) or a git-<subcommand> program (git-commit);
- git named in the words of another program (find -exec, python -c, a script given git as an argument);
- a commit run by a wrapper (env, sudo, xargs, bash -c, eval...), with environment variables, or with a word the
  shell makes when it runs ($ { } * ? [ ~);
- git with a subcommand that is not a known builtin (an alias may be a commit) or one that commits by another way
  (cherry-pick, merge, revert, am, rebase, pull, commit-tree, update-ref);
- a commit joined to another command, with a global option other than -C, or an option of commit outside the list
  above (an abbreviated --amen is outside it too).
A line where git only reads or stages (status, diff, add, push...) is no commit.
git_actions (git_cli.py): every git command of the line, for the git rules (gear/detect/git.py)."""
import os
import re

from harness.gear.translate.git_cli import git_actions
from harness.utils.contracts import Translator
from harness.utils.shell.words import program, read as read_shell

GIT = re.compile(r"(?<![\w.-])git(?:\.exe)?(?![\w.-])", re.I)
NO_COMMIT = {"add", "status", "diff", "log", "show", "branch", "checkout", "switch", "restore", "reset", "fetch",
             "push", "remote", "stash", "tag", "rev-parse", "ls-files", "ls-tree", "blame", "grep", "init", "clone",
             "mv", "rm", "describe", "shortlog", "reflog", "cat-file", "hash-object", "help", "version", "clean",
             "rev-list", "for-each-ref", "symbolic-ref", "name-rev", "diff-tree", "diff-index", "diff-files",
             "count-objects", "check-ignore", "var", "whatchanged", "format-patch", "apply", "fsck", "gc"}
SAFE_SHORT = set("qsv")
VALUE_SHORT = set("mF")
SAFE_LONG = {"--quiet", "--signoff", "--verbose", "--allow-empty"}
VALUE_LONG = {"--message", "--file"}
SHELL_TOOLS = {"Bash": "bash", "PowerShell": "powershell", "HarnessGit": "bash"}  # HarnessGit: the git block's own


def commit_flags(args):
    """Why the options of a commit are unsafe, or ""."""
    j = 0
    while j < len(args):
        arg = args[j]
        if arg.startswith("--"):
            name = arg.split("=", 1)[0]
            if name in VALUE_LONG:
                j += 1 if "=" in arg else 2
                continue
            if name not in SAFE_LONG or "=" in arg:
                return f"{name} is not an option the gate allows on a commit"
        elif arg.startswith("-") and len(arg) > 1:
            letters = arg[1:]
            for k, letter in enumerate(letters):
                if letter in VALUE_SHORT:
                    j += 1 if k == len(letters) - 1 else 0
                    break
                if letter not in SAFE_SHORT:
                    return f"-{letter} is not an option the gate allows on a commit"
        else:
            return f"the commit names paths ({arg})"
        j += 1
    return ""


def git_command(words, cwd):
    """For a command whose program is git: None when it makes no commit, else (repository, why it is unsafe or "")."""
    repo, unsafe, i = cwd, "", 1
    while i < len(words) and words[i].startswith("-"):
        if words[i] == "-C" and i + 1 < len(words):
            repo = os.path.join(repo, words[i + 1])
            i += 2
            continue
        unsafe = unsafe or f"git {words[i].split('=', 1)[0]} is not an option the gate allows"
        i += 2 if words[i] in ("-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--exec-path") else 1
    sub = words[i] if i < len(words) else ""
    if sub in NO_COMMIT:
        return None
    if sub != "commit":
        unsafe = f"git {sub or '(nothing)'} may commit (an alias, or another way to commit): the gate allows git commit only"
    else:
        unsafe = unsafe or commit_flags(words[i + 1:])
    return os.path.normpath(repo).replace("\\", "/"), unsafe


def holds_git(text):
    flat = text.lower()
    for mark in "\"'\\":
        flat = flat.replace(mark, "")
    return "git" in flat


def read(text, cwd, dialect="bash"):
    """{"repo", "unsafe"} when the line may commit, else None."""
    if not holds_git(text):
        return None
    unsafe = {"repo": cwd, "unsafe": ""}
    line = read_shell(text, dialect)
    if line.unread:
        return {**unsafe, "unsafe": f"a line with git that the reader cannot see whole ({line.unread[0]})"}
    found = None
    for command in line.commands:
        if not command.words:
            continue
        first = command.words[0]
        name, bare = program(first.text), program(first.text.replace("\\", ""))
        if first.dynamic or (bare == "git" and name != "git") or bare.startswith("git-"):
            return {**unsafe, "unsafe": f"{first.text} is not git: run git itself"}
        if name != "git":
            if any(GIT.search(w.text) for w in command.args):
                return {**unsafe, "unsafe": "git run by another program"}
            continue
        commit = git_command([w.text for w in command.words], cwd)
        if commit:
            repo, why = commit
            if command.via:
                why = why or f"git run by another program ({', '.join(command.via)}): run git itself"
            why = why or ("environment variables before git" if command.env else "")
            if any(w.dynamic for w in command.words):
                why = why or "a commit with a word the shell makes when it runs ($ { } * ? [ ~)"
            found = {"repo": repo, "unsafe": why}
    if found and len(line.commands) > 1:
        found["unsafe"] = found["unsafe"] or "the commit is joined to another command: run it alone"
    return found


class GitCommands(Translator):
    def translate(self, event):
        if event.tool not in SHELL_TOOLS or not isinstance(event.input.get("command"), str):
            return {}
        cwd = (event.cwd or os.getcwd()).replace("\\", "/")
        found = read(event.input["command"], cwd, SHELL_TOOLS[event.tool])
        actions = git_actions(event.input["command"], cwd, SHELL_TOOLS[event.tool])
        return {**({"git_commit": found} if found else {}), **({"git_actions": actions} if actions else {})}
