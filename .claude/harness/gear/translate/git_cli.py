"""git_actions: every git command of a shell line, as {sub, args, repo, globals, dynamic}: its subcommand, the words
after it, the repository it runs in (-C followed), the global options other than -C it was given, and whether a word
of it is made by the shell when it runs. A line holding git that the reader cannot see whole is [{"unread": why}]."""
from __future__ import annotations

import os
from typing import TypedDict

from harness.utils.shell.words import program, read as read_shell

VALUE_GLOBALS = ("-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--exec-path")


class GitAction(TypedDict, total=False):
    """One git command of a shell line: sub its subcommand ("" when none), args the words after it, repo the
    repository it runs in (-C followed, forward slashes), globals the global options other than -C (names only),
    dynamic whether a word of it is made by the shell when it runs. A line the reader cannot see whole gives one
    GitAction with only unread (why)."""
    sub: str
    args: list[str]
    repo: str
    globals: list[str]
    dynamic: bool
    unread: str


def holds_git(text: str) -> bool:
    """Whether a shell line may hold git: "git" in it, lower case, with quotes and backslashes taken out.

    Args:
        text: the shell line.

    Returns:
        True when the line may run git (so g""it counts).
    """
    flat = text.lower()
    for mark in "\"'\\":
        flat = flat.replace(mark, "")
    return "git" in flat


def action_of(words: list[str], cwd: str, dynamic: bool) -> GitAction:
    """The GitAction of one command whose program is git.

    Args:
        words: the command's words, git first.
        cwd: the folder the line runs in.
        dynamic: whether a word of the command is made by the shell when it runs.

    Returns:
        Its GitAction: sub, args, globals, repo and dynamic.
    """
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


def git_actions(text: str, cwd: str, dialect: str = "bash") -> list[GitAction]:
    """Every git command of a shell line.

    Args:
        text: the shell line.
        cwd: the folder it runs in (forward slashes).
        dialect: the shell that reads it: "bash" or "powershell".

    Returns:
        One GitAction per command whose program is git, in order; [] when the line holds no git; one GitAction with
        only unread when the line holds git and the reader cannot see it whole.
    """
    if not holds_git(text):
        return []
    line = read_shell(text, dialect)
    if line.unread:
        return [{"unread": f"a line with git that the reader cannot see whole ({line.unread[0]})"}]
    return [action_of([w.text for w in c.words], cwd, any(w.dynamic for w in c.words))
            for c in line.commands if c.words and program(c.words[0].text) == "git"]
