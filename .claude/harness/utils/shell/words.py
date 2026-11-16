"""Shell: a command line read the way its shell reads it, then taken out of its wrappers, so a gate sees the commands
that really run. It reads text and never runs it; it knows no rule.

read(text, dialect) gives a Line: the commands, or nothing and why when the line cannot be seen whole (unread).
  dialect   "bash" (the Bash tool, Git Bash on Windows), "powershell", "cmd"
  Command   words (Word: text, dynamic), env (assignments before it), redirects [(op, Word)], heredoc (its body),
            dialect, via (the wrappers taken off, outermost first), stdin_args (xargs gives it more words)
  dynamic   a word whose value the shell makes when it runs: a variable, a glob, ~, a brace or an array
Unread, never guessed: a quote left open, a command run inside a word ($( ), backticks, <( ), PowerShell $( ) or
@( )), a subshell or a group, a heredoc that runs code or has no end, an option of a wrapper the reader does not know,
a string run by a shell that is dynamic, wrappers nested deeper than DEPTH strings.

Wrappers: sudo, env, nohup, time, command, exec, nice, timeout, stdbuf, builtin, xargs run the words after their own
options; sh/bash/zsh/dash/ksh -c, eval, powershell/pwsh -Command and cmd /c run a string, read again in its dialect;
a shell with no argument runs its heredoc. A wrapper's redirections and environment stay on what it runs."""
from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Optional

from harness.utils.shell.command import Command, Unread, Word
from harness.utils.shell.scan import NAME, scan

DEPTH = 4  # strings inside strings: sh -c "eval '...'" is two


@dataclass
class Line:
    """A line read: the commands that really run, or none and why the line cannot be seen whole (unread)."""
    commands: list[Command]
    unread: list[str]


def program(word: str) -> str:
    """The program a word names: its base name, lower case, without .exe.

    Args:
        word: a command's first word (a name or a path, / or \\).

    Returns:
        The program's name ("git" for C:/Program Files/Git/bin/git.exe).
    """
    name = os.path.basename(word.replace("\\", "/")).lower()
    return name[:-4] if name.endswith(".exe") else name


@dataclass(frozen=True)
class Options:
    """The options of a wrapper: flags (no value), values (an option followed by its value), and how its command
    starts."""
    flags: frozenset[str] = frozenset()
    values: frozenset[str] = frozenset()
    positional: int = 0  # words between the options and the command (the duration of timeout)
    assign: bool = False  # NAME=value words set the environment (env)
    numeric: bool = False  # -<n> is an option (nice -5)


def opts(flags: str = "", values: str = "", **kw: Any) -> Options:
    """The Options of a wrapper, written short.

    Args:
        flags: the flags, separated by spaces.
        values: the options with a value, separated by spaces.
        **kw: positional, assign or numeric (Options fields).

    Returns:
        The Options.
    """
    return Options(frozenset(flags.split()), frozenset(values.split()), **kw)


WRAPPERS = {
    "sudo": opts("-E -H -n -S -k -b -P -A -i -s --preserve-env --non-interactive --login --shell",
                 "-u -g -C -D -h -p -U -r -t --user --group"),
    "env": opts("-i -0 --ignore-environment --null", "-u --unset", assign=True),
    "nohup": opts(),
    "time": opts("-p"),
    "command": opts("-p"),
    "exec": opts("-c -l", "-a"),
    "nice": opts("", "-n --adjustment", numeric=True),
    "timeout": opts("--preserve-status --foreground -v --verbose", "-s -k --signal --kill-after", positional=1),
    "stdbuf": opts("", "-i -o -e --input --output --error"),
    "builtin": opts(),
    "xargs": opts("-0 -r -t -p -x --null --no-run-if-empty --verbose --interactive --exit",
                  "-n -L -I -d -P -s -a -E --max-args --max-lines --replace --delimiter --max-procs --max-chars "
                  "--arg-file --eof"),
}
SHELLS = ("sh", "bash", "zsh", "dash", "ksh")
SHELL_LONG = ("--norc", "--noprofile", "--login", "--posix")
POWERSHELL = ("powershell", "pwsh")
PS_FLAGS = ("-noprofile", "-nop", "-noninteractive", "-noni", "-nologo", "-mta", "-sta")
PS_VALUES = ("-executionpolicy", "-ep", "-ex", "-inputformat", "-outputformat", "-windowstyle", "-w")
CMD_FLAGS = ("/d", "/q", "/s", "/a", "/u")


def skip_options(name: str, words: Sequence[Word], spec: Options) -> tuple[list[str], Sequence[Word]]:
    """(environment set by the wrapper, the words of the command it runs).

    Args:
        name: the wrapper's program name.
        words: the words after the wrapper's name.
        spec: the wrapper's options.

    Returns:
        (the NAME=value words it sets, the words of the command it runs).

    Raises:
        Unread: a dynamic word, an unknown option, or no word left for its command.
    """
    env, i = [], 0
    while i < len(words):
        word = words[i]
        w = word.text
        if word.dynamic:
            raise Unread(f"{name} has a word the shell makes ({w})")
        if w == "--":
            i += 1
            break
        if spec.assign and "=" in w and NAME.match(w.split("=", 1)[0]):
            env.append(w)
        elif not w.startswith("-") or w == "-":
            break
        elif w in spec.flags or (spec.numeric and w[1:].isdigit()):
            pass
        elif w in spec.values:
            i += 1
        elif not (w[:2] in spec.values and len(w) > 2 and not w.startswith("--")) \
                and not ("=" in w and w.split("=", 1)[0] in spec.values):
            raise Unread(f"{name} {w} is an option the reader does not know")
        i += 1
    i += spec.positional
    if i > len(words):
        raise Unread(f"{name} is missing a word before its command")
    return env, words[i:]


def shell_string(name: str, words: Sequence[Word], heredoc: Optional[str]) -> Optional[Word]:
    """The string a shell runs (-c), its heredoc when it has no argument, or None when it runs a script.

    Args:
        name: the shell's program name (sh, bash...).
        words: the words after its name.
        heredoc: the body of its heredoc, or None.

    Returns:
        The word of the string it runs, its heredoc as a Word, or None.

    Raises:
        Unread: an unknown long option, or -c with no command.
    """
    i, has_c = 0, False
    while i < len(words) and words[i].text[:1] in "-+" and words[i].text not in ("-", "+"):
        w = words[i].text
        if w in ("-o", "+o", "-O", "+O"):
            i += 1
        elif w.startswith("--"):
            if w not in SHELL_LONG:
                raise Unread(f"{name} {w} is an option the reader does not know")
        else:
            has_c = has_c or "c" in w[1:]
        i += 1
    if has_c:
        if i >= len(words):
            raise Unread(f"{name} -c with no command")
        return words[i]
    if i >= len(words) and heredoc is not None:
        return Word(heredoc)
    return None


def powershell_string(name: str, words: Sequence[Word]) -> Optional[Sequence[Word]]:
    """The words of the command a PowerShell runs (-Command, or the first word for powershell).

    Args:
        name: the first word of the command as written (powershell, pwsh.exe...).
        words: the words after it.

    Returns:
        The words of its command, or None when it runs a file or has no command.

    Raises:
        Unread: an encoded command, or an option the reader does not know.
    """
    for i, word in enumerate(words):
        w = word.text.lower()
        if w in PS_FLAGS:
            continue
        if w in PS_VALUES:
            continue  # its value is the next word, which is no option and is skipped below
        if i > 0 and words[i - 1].text.lower() in PS_VALUES:
            continue
        if w.startswith("-c") and "-command".startswith(w):
            return words[i + 1:]
        if w.startswith("-e") and "-encodedcommand".startswith(w) or w == "-ec":
            raise Unread(f"{name} {word.text} runs an encoded command")
        if w.startswith("-f") and "-file".startswith(w):
            return None
        if not w.startswith("-"):
            return words[i:] if program(name) == "powershell" else None
        raise Unread(f"{name} {word.text} is an option the reader does not know")
    return None


def cmd_string(words: Sequence[Word]) -> Optional[Sequence[Word]]:
    """The words of the command cmd runs (/c or /k).

    Args:
        words: the words after cmd.

    Returns:
        The words after /c or /k, or None when there is none.

    Raises:
        Unread: an option the reader does not know.
    """
    for i, word in enumerate(words):
        w = word.text.lower()
        if w in ("/c", "/k"):
            return words[i + 1:]
        if not (w in CMD_FLAGS or w[:3] in ("/e:", "/f:", "/v:")):
            raise Unread(f"cmd {word.text} is an option the reader does not know")
    return None


def joined(name: str, words: Sequence[Word]) -> str:
    """The string a wrapper runs, its words joined by spaces.

    Args:
        name: the wrapper's name.
        words: the words of the string.

    Returns:
        The string.

    Raises:
        Unread: a word is dynamic.
    """
    if any(w.dynamic for w in words):
        raise Unread(f"{name} runs a string the shell makes when it runs")
    return " ".join(w.text for w in words)


def inner(outer: Command, text: str, dialect: str, label: str, depth: int) -> list[Command]:
    """The commands of a string a wrapper runs, each carrying the wrapper's redirections and environment.

    Args:
        outer: the wrapper's command.
        text: the string it runs.
        dialect: the dialect the string is read in.
        label: how the wrapper runs it, added to via ("bash -c", "eval"...).
        depth: how many strings deep the wrapper already is.

    Returns:
        The commands that really run for the string.

    Raises:
        Unread: deeper than DEPTH, or the string cannot be seen whole.
    """
    if depth >= DEPTH:
        raise Unread(f"strings run inside strings deeper than {DEPTH}")
    out = []
    for command in scan(text, dialect):
        command = replace(command, env=outer.env + command.env, redirects=command.redirects + outer.redirects,
                          via=outer.via + (label,), stdin_args=outer.stdin_args or command.stdin_args)
        out += unwrap(command, depth + 1)
    return out


def unwrap(command: Command, depth: int = 0) -> list[Command]:
    """The commands that really run for command, its wrappers taken off.

    Args:
        command: a command as scanned.
        depth: how many strings deep it is.

    Returns:
        The commands that run (the command itself when it is no wrapper).

    Raises:
        Unread: a wrapper the reader cannot follow.
    """
    if not command.words or command.words[0].dynamic:
        return [command]
    name = program(command.name)
    rest = command.args
    if name in WRAPPERS:
        if name == "command" and any(w.text in ("-v", "-V") for w in rest):
            return [command]
        env, words = skip_options(name, rest, WRAPPERS[name])
        if not words:
            if name != "xargs":
                return [command]
            words = [Word("echo")]
        return unwrap(replace(command, words=list(words), env=command.env + env, via=command.via + (name,),
                              stdin_args=command.stdin_args or name == "xargs"), depth)
    if command.dialect == "bash" and name in SHELLS:
        string = shell_string(name, rest, command.heredoc)
        if string is None:
            return [command]
        heredoc_run = not rest
        return inner(replace(command, heredoc=None) if heredoc_run else command, joined(name, [string]), "bash",
                     f"{name} <<" if heredoc_run else f"{name} -c", depth)
    if name == "eval":
        return inner(command, joined(name, rest), command.dialect, "eval", depth)
    if name in POWERSHELL:
        words = powershell_string(command.name, rest)
        if words is None:
            return [command]
        if [w.text for w in words] in ([], ["-"]):
            raise Unread(f"{command.name} -Command with no command, or one read from stdin")
        return inner(command, joined(name, words), "powershell", f"{name} -Command", depth)
    if name == "cmd":
        words = cmd_string(rest)
        if words is None:
            return [command]
        return inner(command, joined(name, words), "cmd", "cmd /c", depth)
    return [command]


def read(text: str, dialect: str = "bash") -> Line:
    """The commands that really run for a line, or no command and why it cannot be seen whole.

    Args:
        text: the line.
        dialect: "bash", "powershell" or "cmd".

    Returns:
        A Line: its commands and no unread, or no command and [why].
    """
    try:
        out = []
        for command in scan(text, dialect):
            out += unwrap(command)
        return Line(out, [])
    except Unread as e:
        return Line([], [str(e)])
