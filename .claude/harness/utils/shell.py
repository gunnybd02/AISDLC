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
import os
from dataclasses import dataclass, replace

from harness.utils.shell_scan import NAME, Unread, Word, scan

DEPTH = 4  # strings inside strings: sh -c "eval '...'" is two


@dataclass
class Line:
    commands: list
    unread: list


def program(word):
    """The program a word names: its base name, lower case, without .exe."""
    name = os.path.basename(word.replace("\\", "/")).lower()
    return name[:-4] if name.endswith(".exe") else name


@dataclass(frozen=True)
class Options:
    flags: frozenset = frozenset()
    values: frozenset = frozenset()
    positional: int = 0  # words between the options and the command (the duration of timeout)
    assign: bool = False  # NAME=value words set the environment (env)
    numeric: bool = False  # -<n> is an option (nice -5)


def opts(flags="", values="", **kw):
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


def skip_options(name, words, spec):
    """(environment set by the wrapper, the words of the command it runs)."""
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


def shell_string(name, words, heredoc):
    """The string a shell runs (-c), its heredoc when it has no argument, or None when it runs a script."""
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


def powershell_string(name, words):
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


def cmd_string(words):
    for i, word in enumerate(words):
        w = word.text.lower()
        if w in ("/c", "/k"):
            return words[i + 1:]
        if not (w in CMD_FLAGS or w[:3] in ("/e:", "/f:", "/v:")):
            raise Unread(f"cmd {word.text} is an option the reader does not know")
    return None


def joined(name, words):
    if any(w.dynamic for w in words):
        raise Unread(f"{name} runs a string the shell makes when it runs")
    return " ".join(w.text for w in words)


def inner(outer, text, dialect, label, depth):
    """The commands of a string a wrapper runs, each carrying the wrapper's redirections and environment."""
    if depth >= DEPTH:
        raise Unread(f"strings run inside strings deeper than {DEPTH}")
    out = []
    for command in scan(text, dialect):
        command = replace(command, env=outer.env + command.env, redirects=command.redirects + outer.redirects,
                          via=outer.via + (label,), stdin_args=outer.stdin_args or command.stdin_args)
        out += unwrap(command, depth + 1)
    return out


def unwrap(command, depth=0):
    """The commands that really run for command, its wrappers taken off."""
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


def read(text, dialect="bash"):
    """The commands that really run for a line, or no command and why it cannot be seen whole."""
    try:
        out = []
        for command in scan(text, dialect):
            out += unwrap(command)
        return Line(out, [])
    except Unread as e:
        return Line([], [str(e)])
