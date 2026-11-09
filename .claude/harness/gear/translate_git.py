"""GitCommands: whether a Bash command commits, and in which repository. A minimal reader until the shell reader moves
in: the command is split into words (quotes kept whole) and into commands at && || ; |; a command whose program is git,
after its global options (-C <dir>, -c <k=v>...), runs the subcommand `commit`."""
import os
import shlex

from harness.utils.contracts import Translator

SEPARATORS = {"&&", "||", ";", "|", "&"}
TAKES_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


def commands(text):
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        return []
    out, current = [], []
    for word in words:
        if word in SEPARATORS:
            out.append(current)
            current = []
        else:
            current.append(word)
    return out + [current]


def commit_repo(words, cwd):
    """The repository a `git ... commit` command commits in, or None when it is no commit."""
    if not words or os.path.basename(words[0]).lower() not in ("git", "git.exe"):
        return None
    repo, i = cwd, 1
    while i < len(words) and words[i].startswith("-"):
        if words[i] == "-C" and i + 1 < len(words):
            repo = os.path.join(repo, words[i + 1])
        i += 2 if words[i] in TAKES_VALUE else 1
    if i < len(words) and words[i] == "commit":
        return os.path.normpath(repo).replace("\\", "/")
    return None


class GitCommands(Translator):
    def translate(self, event):
        if event.tool != "Bash" or not isinstance(event.input.get("command"), str):
            return {}
        cwd = event.cwd or os.getcwd()
        for words in commands(event.input["command"]):
            repo = commit_repo(words, cwd)
            if repo:
                return {"git_commit": {"repo": repo}}
        return {}
