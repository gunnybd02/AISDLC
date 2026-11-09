"""GitCommands: whether a Bash command commits, in which repository, and whether the gate can see the whole commit.
A minimal reader until the shell reader moves in, built to fail closed: what it does not understand is unsafe.

A commit is safe only as one plain command on one line:
    git [-C <dir>]... commit [-m <msg> | -F <file> | -q | -s | -v | --allow-empty | --message=.. | --file=..]...
Everything else that can make a commit is unsafe ({"unsafe": why}):
- a line holding git (quotes and backslashes taken out, so g""it counts) that also holds a newline, $( or a backtick,
  ( or { , or does not parse;
- a line holding git and one of $ { } * ? [ ~ % (expansions the shell does before git sees the words), unless it is
  one plain git command that makes no commit (git log --format=%H);
- a first word that is git spelled another way (g\\it) or a git-<subcommand> program (git-commit); quotes inside
  a word are read as the shell reads them, so g""it is git itself and is judged as git;
- git run by another program (env, time, sudo, xargs, eval, bash -c, python -c ...), anywhere in the line;
- git with a subcommand that is not a known builtin (an alias may be a commit) or one that commits by another way
  (cherry-pick, merge, revert, am, rebase, pull, commit-tree, update-ref);
- a commit joined to another command, carrying environment variables, with a global option other than -C, or an
  option of commit outside the list above (an abbreviated --amen is outside it too).
A line where git only reads or stages (status, diff, add, push...) is no commit."""
import os
import re
import shlex

from harness.utils.contracts import Translator

SEPARATORS = {"&&", "||", ";", "|", "&"}
GROUPS = {"(", ")", "{", "}"}
GIT = re.compile(r"(?<![\w.-])git(?:\.exe)?(?![\w.-])", re.I)
COMMITS = {"commit", "cherry-pick", "merge", "revert", "am", "rebase", "pull", "commit-tree", "update-ref"}
NO_COMMIT = {"add", "status", "diff", "log", "show", "branch", "checkout", "switch", "restore", "reset", "fetch",
             "push", "remote", "stash", "tag", "rev-parse", "ls-files", "ls-tree", "blame", "grep", "init", "clone",
             "mv", "rm", "describe", "shortlog", "reflog", "cat-file", "hash-object", "help", "version", "clean",
             "rev-list", "for-each-ref", "symbolic-ref", "name-rev", "diff-tree", "diff-index", "diff-files",
             "count-objects", "check-ignore", "var", "whatchanged", "format-patch", "apply", "fsck", "gc"}
SAFE_SHORT = set("qsv")
VALUE_SHORT = set("mF")
SAFE_LONG = {"--quiet", "--signoff", "--verbose", "--allow-empty"}
VALUE_LONG = {"--message", "--file"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
EXPANSIONS = set("${}*?[~%")
SHELL_TOOLS = ("Bash", "PowerShell")


def program(word):
    name = os.path.basename(word.replace("\\", "/")).lower()
    return name[:-4] if name.endswith(".exe") else name


def commands(text):
    """The words of each command of the line; ValueError when the line does not parse."""
    lexer = shlex.shlex(text.replace("\\", "\\\\"), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    out, current = [], []
    for word in lexer:
        if word in SEPARATORS:
            out.append(current)
            current = []
        else:
            current.append(word)
    return [c for c in out + [current] if c]


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


def read(text, cwd):
    """{"repo", "unsafe"} when the line may commit, else None."""
    if not holds_git(text):
        return None
    unsafe = {"repo": cwd, "unsafe": ""}
    if "\n" in text or "\r" in text or "$(" in text or "`" in text:
        return {**unsafe, "unsafe": "a line with git may not hold a newline, $( or a backtick"}
    try:
        lines = commands(text)
    except ValueError:
        return {**unsafe, "unsafe": "the command does not parse"}
    if EXPANSIONS & set(text):
        plain = len(lines) == 1 and lines[0][0] == "git" and git_command(lines[0], cwd) is None
        return None if plain else {**unsafe, "unsafe": "a line with git may not hold $ { } * ? [ ~ % (shell expansions)"}
    found = None
    for words in lines:
        envs = 0
        while envs < len(words) and ASSIGNMENT.match(words[envs]):
            envs += 1
        rest = words[envs:]
        if not rest:
            continue
        bare = program(rest[0].replace("\\", ""))
        if (bare == "git" and program(rest[0]) != "git") or bare.startswith("git-"):
            return {**unsafe, "unsafe": f"{rest[0]} is not git: run git itself"}
        if any(w in GROUPS for w in rest) or any(GIT.search(w) for w in rest[1:] if program(rest[0]) != "git"):
            return {**unsafe, "unsafe": "git run inside a group or by another program"}
        if program(rest[0]) != "git":
            continue
        commit = git_command(rest, cwd)
        if commit:
            found = {"repo": commit[0], "unsafe": commit[1] or ("environment variables before git" if envs else "")}
    if found and len(lines) > 1:
        found["unsafe"] = found["unsafe"] or "the commit is joined to another command: run it alone"
    return found


class GitCommands(Translator):
    def translate(self, event):
        if event.tool not in SHELL_TOOLS or not isinstance(event.input.get("command"), str):
            return {}
        found = read(event.input["command"], (event.cwd or os.getcwd()).replace("\\", "/"))
        return {"git_commit": found} if found else {}
