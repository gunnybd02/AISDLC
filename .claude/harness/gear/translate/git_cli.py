"""git_actions: every git command of a shell line, as {sub, args, repo, globals, dynamic}: its subcommand, the words
after it, the repository it runs in (-C followed), the global options other than -C it was given, and whether a word
of it is made by the shell when it runs. A line holding git that the reader cannot see whole is [{"unread": why}]."""
import os

from harness.utils.shell.words import program, read as read_shell

VALUE_GLOBALS = ("-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--exec-path")


def holds_git(text):
    flat = text.lower()
    for mark in "\"'\\":
        flat = flat.replace(mark, "")
    return "git" in flat


def action_of(words, cwd, dynamic):
    repo, globs, i = cwd, [], 1
    while i < len(words) and words[i].startswith("-"):
        if words[i] == "-C" and i + 1 < len(words):
            repo = os.path.join(repo, words[i + 1])
            i += 2
            continue
        globs.append(words[i].split("=", 1)[0])
        i += 2 if words[i] in VALUE_GLOBALS else 1
    return {"sub": words[i] if i < len(words) else "", "args": words[i + 1:], "globals": globs,
            "repo": os.path.normpath(repo).replace("\\", "/"), "dynamic": dynamic}


def git_actions(text, cwd, dialect="bash"):
    if not holds_git(text):
        return []
    line = read_shell(text, dialect)
    if line.unread:
        return [{"unread": f"a line with git that the reader cannot see whole ({line.unread[0]})"}]
    return [action_of([w.text for w in c.words], cwd, any(w.dynamic for w in c.words))
            for c in line.commands if c.words and program(c.words[0].text) == "git"]
