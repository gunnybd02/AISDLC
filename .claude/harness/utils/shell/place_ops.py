"""The files a shell line writes. Each command that really runs is looked up in the tables: a known read writes
nothing; a known write names its files (its operands, a redirection, the destination of a copy, the file of a
download); anything else is unread. After cd X, a relative path is read both from the folder before and from X.
The bash and cmd writes are in write_ops.py, the PowerShell cmdlets in cmdlets.py."""
from __future__ import annotations

import os
from collections.abc import Sequence

from harness.utils.shell.cmdlets import CMDLETS, PS_ALIASES, PS_READS, cmdlet
from harness.utils.shell.command import Command
from harness.utils.shell.git_ops import git
from harness.utils.shell.mentions import harness_own
from harness.utils.shell.paths import Target, Unseen, absolute
from harness.utils.shell.words import program, read
from harness.utils.shapes import Facts
from harness.utils.shell.write_ops import BASH_WRITES, CMD_WRITES, INTERPRETERS, interpreter

BENIGN = {"/dev/null", "/dev/stdout", "/dev/stderr", "nul", "$null", "con"}
OUT_OPS = {">", ">>", ">|", "&>", "&>>", "<>"}

READS = frozenset((
    "ls dir cat head tail less more grep egrep fgrep rg wc diff cmp echo printf pwd which where whereis type file "
    "stat du df whoami true false test [ basename dirname realpath readlink cut tr column nl od jq uname id ps env "
    "printenv sleep seq md5sum sha1sum sha256sum cksum findstr ver").split())
CD = {"cd", "chdir", "set-location"}
READ_RUNS = {"rg": ("--pre",), "sort": ("--compress-program",)}  # options that make a known command run a program


def command_targets(command: Command) -> list[Target]:
    """The places one command writes; Unseen when they cannot be told.

    Args:
        command: a command that really runs (wrappers taken off).

    Returns:
        Its writes and those of its redirections.

    Raises:
        Unseen: a command the shell makes, an unknown command, an option that runs a program, xargs naming the
            files, or what its entry cannot tell.
    """
    if not command.words:
        return redirect_targets(command)
    if command.words[0].dynamic:
        raise Unseen(f"the command {command.name} is made by the shell when it runs")
    name, ws = program(command.name), command.args
    if harness_own(command):  # the harness's own CLI writes only through the harness, as it is meant to
        return redirect_targets(command)
    if command.dialect == "powershell":
        name = PS_ALIASES.get(name, name)
        reads, writes = PS_READS, CMDLETS
    else:
        reads, writes = READS, CMD_WRITES if command.dialect == "cmd" else BASH_WRITES
    runs = [w.text for w in ws if w.text.startswith(READ_RUNS.get(name, ("\0",)))]
    if runs:
        raise Unseen(f"{command.name} {runs[0]} runs a program")
    if name in reads:
        return redirect_targets(command)
    if name == "git":
        return git(ws) + redirect_targets(command)
    if name in INTERPRETERS and command.dialect == "bash":
        return interpreter(name, INTERPRETERS[name])(ws, command.heredoc) + redirect_targets(command)
    if name not in writes:
        raise Unseen(f"{command.name} is a command the reader does not know")
    if command.stdin_args:
        raise Unseen(f"xargs gives {command.name} the names of the files it changes")
    found = cmdlet(name, writes[name], ws) if command.dialect == "powershell" else writes[name](ws)
    return found + redirect_targets(command)


def redirect_targets(command: Command) -> list[Target]:
    """The places a command's redirections write (>, >>, &>...; a file descriptor and BENIGN left out).

    Args:
        command: a command that really runs.

    Returns:
        A Target for each output redirection.
    """
    out = []
    for op, word in command.redirects:
        fd = op == ">&" and (word.text.isdigit() or word.text == "-")
        if (op in OUT_OPS or op == ">&" and not fd) and word.text.lower() not in BENIGN:
            out.append(Target(word))
    return out


def resolve(target: Target, cwds: Sequence[str], dialect: str) -> list[str]:
    """The absolute paths a target names from each folder the line may be in.

    Args:
        target: a place a command writes.
        cwds: the folders the command may run in.
        dialect: the command's dialect.

    Returns:
        The paths with forward slashes (a folder target gives the files of its names inside it).

    Raises:
        Unseen: the target is made by the shell when it runs.
    """
    if target.word.dynamic:
        raise Unseen(f"the target {target.word.text} is made by the shell when it runs")
    out = []
    for cwd in cwds:
        path = absolute(target.word.text, cwd, dialect)
        folder = target.names and (target.word.text.endswith(("/", "\\")) or os.path.isdir(path))
        out += [f"{path}/{n}" for n in target.names] if folder else [path]
    return out


def cd_folder(command: Command) -> str:
    """The folder a cd command goes to.

    Args:
        command: a cd, chdir or Set-Location command.

    Returns:
        Its one argument as written.

    Raises:
        Unseen: not one argument, a dynamic one, - or ~.
    """
    ws = [w for w in command.args if w.text.lower() != "/d"]
    if len(ws) != 1 or ws[0].dynamic or ws[0].text in ("-", "~"):
        raise Unseen(f"{command.name} to a folder the reader does not know")
    return ws[0].text


def shell_places(command_line: str, dialect: str, cwd: str, said: str) -> Facts:
    """The facts of a shell line's writes.

    Args:
        command_line: the shell line.
        dialect: "bash", "powershell" or "cmd".
        cwd: the folder the line starts in.
        said: the agent's words on what the line does (the tool's description; "" when none).

    Returns:
        {"writes": sorted absolute paths} when it writes, and when part of it is unread also shell_unread (the
        reasons), shell_command (the line), shell_said (said) and shell_dirs (every folder it may run in, after its
        cd commands); {} for a line that writes nothing it can see.
    """
    line = read(command_line, dialect)
    unread, writes, cwds = list(line.unread), [], [cwd]
    for command in line.commands:
        try:
            name = program(command.name) if command.words and not command.words[0].dynamic else ""
            if PS_ALIASES.get(name, name) in CD or name == "cd":
                folder = cd_folder(command)
                cwds = list(dict.fromkeys(cwds + [absolute(folder, c, command.dialect) for c in cwds]))
                continue
            for target in command_targets(command):
                writes += resolve(target, cwds, command.dialect)
        except Unseen as e:
            unread.append(str(e))
    facts = {"writes": sorted(set(writes))} if writes else {}
    if unread:
        facts.update(shell_unread=unread, shell_command=command_line, shell_said=said, shell_dirs=cwds)
    return facts
