"""The files a shell line writes. Each command that really runs is looked up in the tables: a known read writes
nothing; a known write names its files (its operands, a redirection, the destination of a copy, the file of a
download); anything else is unread. After cd X, a relative path is read both from the folder before and from X."""
import os
import re
from dataclasses import dataclass

from harness.utils.shell.git_ops import git
from harness.utils.shell.paths import Target, Unseen, absolute
from harness.utils.shell.scan import Word
from harness.utils.shell.words import program, read

BENIGN = {"/dev/null", "/dev/stdout", "/dev/stderr", "nul", "$null", "con"}
OUT_OPS = {">", ">>", ">|", "&>", "&>>", "<>"}

READS = frozenset((
    "ls dir cat head tail less more grep egrep fgrep rg wc diff cmp echo printf pwd which where whereis type file "
    "stat du df whoami true false test [ basename dirname realpath readlink cut tr column nl od jq uname id ps env "
    "printenv sleep seq md5sum sha1sum sha256sum cksum findstr ver").split())
PS_READS = frozenset((
    "get-childitem get-content get-item get-location select-string write-output write-host test-path resolve-path "
    "get-command measure-object sort-object select-object format-table format-list get-date get-process out-host "
    "out-string out-null convertto-json convertfrom-json get-filehash split-path join-path get-help").split())
PS_ALIASES = {
    **dict.fromkeys(("rm", "del", "erase", "rd", "rmdir", "ri"), "remove-item"),
    **dict.fromkeys(("mkdir", "md", "ni"), "new-item"),
    **dict.fromkeys(("cp", "copy", "cpi"), "copy-item"),
    **dict.fromkeys(("mv", "move", "mi"), "move-item"),
    **dict.fromkeys(("cd", "sl", "chdir"), "set-location"),
    **dict.fromkeys(("ls", "dir", "gci"), "get-childitem"),
    **dict.fromkeys(("cat", "gc", "type"), "get-content"),
    **dict.fromkeys(("echo", "write"), "write-output"),
    **dict.fromkeys(("pwd", "gl"), "get-location"),
    "sc": "set-content", "ac": "add-content", "clc": "clear-content", "tee": "tee-object",
}
CD = {"cd", "chdir", "set-location"}
FIND_ACTIONS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}
INTERPRETERS = {"python": ("-c",), "python3": ("-c",), "py": ("-c",), "node": ("-e", "-p", "--eval", "--print"),
                "ruby": ("-e",), "php": ("-r",), "perl": ("-e", "-E")}
WRITE_API = re.compile(
    r"writeFile|appendFile|createWriteStream|\.write\(|copyFile|cpSync|rename|unlink|\brm\b|rmSync|rmdir|mkdir|"
    r"truncate|chmod|open\(|fs\.\w*write|write_text|write_bytes|shutil\.|os\.remove|os\.replace|\.touch\(|"
    r"subprocess|system|popen|child_process|\bexec|\beval|spawn|Set-Content|Out-File|Remove-Item|>|"
    r"__|getattr|\bimport\b|require|process|Kernel|\bsend\b|ctypes", re.I)
READ_RUNS = {"rg": ("--pre",), "sort": ("--compress-program",)}  # options that make a known command run a program
SED_RUNS =re.compile(r"(^|[;\n{}/]|\d|\$)\s*[wWe](\s|$)")



def operands(words, values=(), flag="-"):
    """The words that are no option, the values of the options named in values skipped."""
    out, i, ended = [], 0, False
    while i < len(words):
        t = words[i].text
        if not ended and t == "--":
            ended = True
        elif not ended and t.startswith(flag) and len(t) > 1 and (flag == "-" or len(t) <= 3):
            i += t in values
        else:
            out.append(words[i])
        i += 1
    return out


def each(values=""):
    return lambda ws: [Target(w) for w in operands(ws, values.split())]


def after_first(ws):
    ops = operands(ws)
    return [Target(w) for w in (ops if any(w.text.startswith("--reference") for w in ws) else ops[1:])]


def base(word):
    return os.path.basename(word.text.replace("\\", "/").rstrip("/"))


def into_last(values="", moves=False, flag="-"):
    """cp, mv, copy: the last operand is the destination (a folder holds the files of the same name)."""
    def targets(ws):
        if any(w.text in ("-t", "--target-directory") or w.text.startswith("--target-directory=") for w in ws):
            raise Unseen("a destination given by -t")
        ops = operands(ws, values.split(), flag)
        if len(ops) < 2:
            raise Unseen("a copy or a move with no destination")
        sources = ops[:-1]
        return [Target(w) for w in sources if moves] + [Target(ops[-1], tuple(base(w) for w in sources))]
    return targets


def ln(ws):
    if any(w.text == "-t" or w.text.startswith("--target-directory") for w in ws):
        raise Unseen("a destination given by -t")
    ops = operands(ws, ("-S", "--suffix"))
    if len(ops) == 1:
        return [Target(Word(base(ops[0])))]
    return [Target(ops[-1], tuple(base(w) for w in ops[:-1]))] if ops else []


def sed(ws):
    in_place, scripts, files, i = False, [], [], 0
    while i < len(ws):
        t = ws[i].text
        if t in ("-e", "--expression", "-f", "--file"):
            scripts.append(ws[i + 1] if i + 1 < len(ws) else Word(""))
            i += 1
        elif t.startswith(("--expression=", "--file=")):
            scripts.append(Word(t.split("=", 1)[1], ws[i].dynamic))
        elif t.startswith("-i") or t.startswith("--in-place") or re.fullmatch(r"-[nrEsuzl]+i", t):
            in_place = True
        elif t.startswith("-") and len(t) > 1:
            if "i" in t and not t.startswith("--"):
                raise Unseen(f"sed {t}: an in-place flag the reader does not follow")
        else:
            files.append(ws[i])
        i += 1
    if not scripts and files:
        scripts.append(files.pop(0))
    if any(w.dynamic or SED_RUNS.search(w.text) for w in scripts):
        raise Unseen("a sed script that writes a file or runs a command (w, e)")
    return [Target(w) for w in files] if in_place else []


def curl(ws):
    out = []
    for i, w in enumerate(ws):
        t, nxt = w.text, ws[i + 1] if i + 1 < len(ws) else None
        if t in ("-o", "--output"):
            out.append(nxt)
        elif t.startswith("--output="):
            out.append(Word(t.split("=", 1)[1], w.dynamic))
        elif t.startswith(("--remote-name", "--output-dir", "--dump-header", "--cookie-jar", "--config")):
            raise Unseen(f"curl {t} writes a file the reader does not name")
        elif t.startswith("-") and not t.startswith("--") and len(t) > 1:
            letters = t[1:]
            if set(letters) & set("OJDcK"):
                raise Unseen(f"curl {t} writes a file the reader does not name")
            if "o" in letters:
                rest = letters[letters.index("o") + 1:]
                out.append(Word(rest, w.dynamic) if rest else nxt)
    if None in out:
        raise Unseen("curl -o with no file")
    return [Target(w) for w in out]


def wget(ws):
    out, named = [], False
    for i, w in enumerate(ws):
        t, nxt = w.text, ws[i + 1] if i + 1 < len(ws) else None
        long = {"--output-document": True, "--output-file": False, "--append-output": False}
        name = t.split("=", 1)[0]
        if name in long:
            named = named or long[name]
            out.append(Word(t.split("=", 1)[1], w.dynamic) if "=" in t else nxt)
        elif t.startswith("-") and not t.startswith("--") and len(t) > 1:
            letters = t[1:]
            if "P" in letters:
                raise Unseen("wget -P saves into a folder")
            for letter in "Ooa":
                if letter in letters:
                    rest = letters[letters.index(letter) + 1:]
                    out.append(Word(rest, w.dynamic) if rest else nxt)
                    named = named or letter == "O"
                    break
    if not named:
        raise Unseen("wget saves a file named by the address")
    if None in out:
        raise Unseen("wget -O with no file")
    return [Target(w) for w in out if w.text != "-"]


def dd(ws):
    return [Target(Word(w.text[3:], w.dynamic)) for w in ws if w.text.startswith("of=")]


def tar(ws):
    first = ws[0].text if ws else ""
    listing = first in ("-t", "--list") or (not first.startswith("--") and "t" in first and not set(first) & set("xcru"))
    if not listing:
        raise Unseen("tar makes or unpacks files the reader does not name")
    return []


def find(ws):
    if any(w.text in FIND_ACTIONS for w in ws):
        raise Unseen("find deletes, runs a command or writes a file")
    return []


def option_value(ws, names):
    for i, w in enumerate(ws):
        for name in names:
            if w.text == name and i + 1 < len(ws):
                return [Target(ws[i + 1])]
            if w.text.startswith(name) and len(w.text) > len(name) and (name.startswith("--") or len(name) == 2):
                return [Target(Word(w.text[len(name):].lstrip("="), w.dynamic))]
    return []


def inline(name, code):
    if code.dynamic or WRITE_API.search(code.text):
        raise Unseen(f"the code {name} runs may write files or run commands")
    return []


def interpreter(name, flags):
    def targets(ws, heredoc):
        if name == "perl" and any(w.text.startswith("-") and not w.text.startswith("--") and "i" in w.text[1:]
                                  for w in ws):
            raise Unseen("perl -i changes files in place")
        i = 0
        while i < len(ws):
            t = ws[i].text
            if t in flags:
                if i + 1 >= len(ws):
                    raise Unseen(f"{name} {t} with no code")
                return inline(name, ws[i + 1])
            if t == "-":
                break
            if t in ("-m", "-r") and name != "php":
                raise Unseen(f"{name} {t} runs a program the reader cannot see into")
            if not t.startswith("-"):
                raise Unseen(f"{name} runs {t}, a program the reader cannot see into")
            i += 2 if t in ("-X", "-W") else 1
        if heredoc is None:
            raise Unseen(f"{name} reads its program from its input")
        return inline(name, Word(heredoc))
    return targets


BASH_WRITES = {
    **dict.fromkeys(("rm", "rmdir", "unlink"), each()),
    "touch": each("-d -t -r --date --reference"), "mkdir": each("-m --mode"), "tee": each(),
    "truncate": each("-s -r --size --reference"), "shred": each("-n -s --iterations --size"),
    **dict.fromkeys(("chmod", "chown", "chgrp"), after_first),
    "cp": into_last("-S --suffix"), "install": into_last("-m -o -g -S --mode --owner --group --suffix"),
    "mv": into_last("-S --suffix", moves=True), "ln": ln, "sed": sed, "curl": curl, "wget": wget, "dd": dd,
    "tar": tar, "find": find,
    "sort": lambda ws: option_value(ws, ("-o", "--output")), "tree": lambda ws: option_value(ws, ("-o",)),
    "uniq": lambda ws: [Target(w) for w in operands(ws, ("-f", "-s", "-w"))[1:2]],
}
CMD_WRITES = {
    **dict.fromkeys(("del", "erase", "rd", "rmdir", "md", "mkdir"), lambda ws: [Target(w) for w in operands(ws, flag="/")]),
    "copy": into_last(flag="/"), "move": into_last(moves=True, flag="/"),
}


@dataclass(frozen=True)
class Cmdlet:
    positional: tuple = ()  # what each word with no parameter name is: path (written), source (read), value
    paths: tuple = ()  # parameters whose value is a written path
    sources: tuple = ()  # parameters whose value is read
    values: tuple = ()  # other parameters with a value
    switches: tuple = ()
    into: bool = False  # the written path may be a folder that gets the sources' names
    piped: bool = False  # with no -Path, -LiteralPath or first word, it takes the items it changes from the pipeline


COMMON_SWITCHES = ("-force", "-whatif", "-confirm", "-passthru", "-verbose")
COMMON_VALUES = ("-erroraction",)
CMDLETS = {
    "remove-item": Cmdlet(("path",), ("-path", "-literalpath"), (), ("-include", "-exclude", "-filter"), ("-recurse",),
                          piped=True),
    "new-item": Cmdlet(("path",), ("-path",), (), ("-itemtype", "-type", "-value")),
    "set-content": Cmdlet(("path", "value"), ("-path", "-literalpath"), (), ("-value", "-encoding"), ("-nonewline",)),
    "add-content": Cmdlet(("path", "value"), ("-path", "-literalpath"), (), ("-value", "-encoding"), ("-nonewline",)),
    "clear-content": Cmdlet(("path",), ("-path", "-literalpath"), piped=True),
    "out-file": Cmdlet(("path",), ("-filepath", "-literalpath", "-path"), (), ("-encoding", "-width", "-inputobject"),
                       ("-append", "-noclobber", "-nonewline")),
    "tee-object": Cmdlet(("path",), ("-filepath", "-literalpath"), (), ("-inputobject",), ("-append",)),
    "copy-item": Cmdlet(("source", "path"), ("-destination",), ("-path", "-literalpath"), (), ("-recurse", "-container"),
                        into=True, piped=True),
    "move-item": Cmdlet(("path", "path"), ("-path", "-literalpath", "-destination"), piped=True),
}


def cmdlet(name, spec, ws):
    written, sources, slot, i, named = [], [], 0, 0, False
    while i < len(ws):
        word = ws[i]
        t = word.text.lower()
        if t.startswith("-") and len(t) > 1:
            key, colon, _ = t.partition(":")
            if key in spec.switches or key in COMMON_SWITCHES:
                i += 1
                continue
            if key not in spec.paths + spec.sources + spec.values + COMMON_VALUES:
                raise Unseen(f"{name} {word.text} is a parameter the reader does not know")
            arg = Word(word.text.partition(":")[2], word.dynamic) if colon else (ws[i + 1] if i + 1 < len(ws) else None)
            if arg is None:
                raise Unseen(f"{name} {word.text} has no value")
            (written if key in spec.paths else sources if key in spec.sources else []).append(arg)
            named = named or key in ("-path", "-literalpath")
            i += 1 if colon else 2
            continue
        kind = spec.positional[slot] if slot < len(spec.positional) else None
        if kind is None:
            raise Unseen(f"{name} has a word the reader does not place ({word.text})")
        (written if kind == "path" else sources if kind == "source" else []).append(word)
        named = named or slot == 0
        slot, i = slot + 1, i + 1
    if spec.piped and not named:
        raise Unseen(f"{name} takes the items it changes from the pipeline")
    names =tuple(base(w) for w in sources) if spec.into else ()
    return [Target(w, names) for w in written]


def command_targets(command):
    """The places one command writes; Unseen when they cannot be told."""
    if not command.words:
        return redirect_targets(command)
    if command.words[0].dynamic:
        raise Unseen(f"the command {command.name} is made by the shell when it runs")
    name, ws = program(command.name), command.args
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


def redirect_targets(command):
    out = []
    for op, word in command.redirects:
        fd = op == ">&" and (word.text.isdigit() or word.text == "-")
        if (op in OUT_OPS or op == ">&" and not fd) and word.text.lower() not in BENIGN:
            out.append(Target(word))
    return out


def resolve(target, cwds, dialect):
    if target.word.dynamic:
        raise Unseen(f"the target {target.word.text} is made by the shell when it runs")
    out = []
    for cwd in cwds:
        path = absolute(target.word.text, cwd, dialect)
        folder = target.names and (target.word.text.endswith(("/", "\\")) or os.path.isdir(path))
        out += [f"{path}/{n}" for n in target.names] if folder else [path]
    return out


def cd_folder(command):
    ws = [w for w in command.args if w.text.lower() != "/d"]
    if len(ws) != 1 or ws[0].dynamic or ws[0].text in ("-", "~"):
        raise Unseen(f"{command.name} to a folder the reader does not know")
    return ws[0].text


def shell_places(command_line, dialect, cwd, said):
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
        facts.update(shell_unread=unread, shell_command=command_line, shell_said=said)
    return facts
