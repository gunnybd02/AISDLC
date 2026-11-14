"""The places a shell line names, read or written, as absolute paths with forward slashes: every word of every command
that really runs (its options' values too, --file=x), its redirections and the values of its variables, each read
from every folder the line may be in (after cd X: from the folder before and from X). A word with a wildcard is
expanded against the disk; a word the shell makes from a variable ($HOME/x) cannot be told and is left out.

The harness's own commands (python -m entry.<x>, python <claude>/entry/<x>.py) name nothing here: they open the
harness's data themselves, which is how it is meant to be opened. A line the reader cannot see whole is read word by
word, so a path in it is still found."""
import glob
import os
import re

from harness.utils.shell.paths import absolute
from harness.utils.shell.words import program, read

PYTHONS = {"python", "python3", "py", "pythonw"}
CD = {"cd", "chdir", "set-location", "pushd", "sl"}
WILD = re.compile(r"[*?\[]")
MADE = re.compile(r"[$`]|%\w+%")


def harness_own(command):
    """Whether the command runs the harness itself: python -m entry.<x>, or python <...>/entry/<x>.py."""
    if program(command.name) not in PYTHONS:
        return False
    args = [w.text for w in command.args]
    if args[:1] == ["-m"] and len(args) > 1:
        return args[1].startswith("entry.")
    return bool(args) and re.search(r"(^|[\\/])entry[\\/]\w+\.py$", args[0]) is not None


def runs_harness(command_line, dialect="bash"):
    """Whether a shell line runs the harness itself in one of its commands (the session's link to the harness's CLI,
    as a call of its MCP tools is)."""
    return any(c.words and not c.words[0].dynamic and harness_own(c) for c in read(command_line, dialect).commands)


def texts(command):
    """The texts of the words that may name a place, options' values split off."""
    out = []
    for text in [w.text for w in command.args if not w.dynamic or not MADE.search(w.text)] + \
            [e.split("=", 1)[1] for e in command.env if "=" in e] + [w.text for _, w in command.redirects]:
        out.append(text)
        if text.startswith("-") and "=" in text:
            out.append(text.split("=", 1)[1])
    return [t for t in out if t and not t.startswith("-") and not MADE.search(t)]


def places(text, cwds, dialect):
    out = []
    for cwd in cwds:
        path = absolute(text, cwd, dialect)
        out += [p.replace("\\", "/") for p in glob.glob(path)] if WILD.search(text) else [path]
    return out


def mentioned(command_line, dialect, cwd):
    line = read(command_line, dialect)
    found, cwds = [], [cwd]
    for command in line.commands:
        if not command.words or command.words[0].dynamic or harness_own(command):
            continue
        for text in texts(command):
            found += places(text, cwds, command.dialect)
        if program(command.name) in CD and command.args and not command.args[0].dynamic:
            cwds = list(dict.fromkeys(cwds + [absolute(command.args[0].text, c, command.dialect) for c in cwds]))
    if line.unread:  # what the reader cannot see whole is read word by word
        for word in re.split(r"[\s;&|()<>'\"]+", command_line):
            if word and not word.startswith("-") and not MADE.search(word):
                found += places(word, cwds, dialect)
    return sorted(set(found))
