"""The writes of the bash and cmd commands the shell reader knows: each entry of BASH_WRITES and CMD_WRITES takes the
words after the command's name and gives the places it writes (Target), or raises Unseen when they cannot be told (a
destination given by -t, a sed script that writes, a download named by its address, code that may write...).
INTERPRETERS names the programs whose inline code is read for a write (python -c, node -e...). place_ops.py looks a
command up here."""
from __future__ import annotations

import os
import re
from collections.abc import Callable, Collection, Sequence
from typing import Optional

from harness.utils.shell.command import Word
from harness.utils.shell.paths import Target, Unseen

Writes = Callable[[Sequence[Word]], list[Target]]
"""An entry of BASH_WRITES or CMD_WRITES: the words after the command's name -> the places it writes."""

FIND_ACTIONS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}
INTERPRETERS = {"python": ("-c",), "python3": ("-c",), "py": ("-c",), "node": ("-e", "-p", "--eval", "--print"),
                "ruby": ("-e",), "php": ("-r",), "perl": ("-e", "-E")}
WRITE_API = re.compile(
    r"writeFile|appendFile|createWriteStream|\.write\(|copyFile|cpSync|rename|unlink|\brm\b|rmSync|rmdir|mkdir|"
    r"truncate|chmod|open\(|fs\.\w*write|write_text|write_bytes|shutil\.|os\.remove|os\.replace|\.touch\(|"
    r"subprocess|system|popen|child_process|\bexec|\beval|spawn|Set-Content|Out-File|Remove-Item|>|"
    r"__|getattr|\bimport\b|require|process|Kernel|\bsend\b|ctypes", re.I)
SED_RUNS =re.compile(r"(^|[;\n{}/]|\d|\$)\s*[wWe](\s|$)")


def operands(words: Sequence[Word], values: Collection[str] = (), flag: str = "-") -> list[Word]:
    """The words that are no option, the values of the options named in values skipped.

    Args:
        words: the words after the command's name.
        values: the options followed by a value.
        flag: what an option starts with ("-", or "/" for cmd, where an option is at most 3 characters).

    Returns:
        The operands in order; every word after -- is one.
    """
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


def each(values: str = "") -> Writes:
    """The writes of a command that writes each of its operands (rm, touch, mkdir, tee...).

    Args:
        values: its options followed by a value, separated by spaces.

    Returns:
        ws -> a Target for each operand.
    """
    return lambda ws: [Target(w) for w in operands(ws, values.split())]


def after_first(ws: Sequence[Word]) -> list[Target]:
    """The writes of chmod, chown, chgrp: every operand after the mode or owner (all of them with --reference).

    Args:
        ws: the words after the command's name.

    Returns:
        A Target for each file changed.
    """
    ops = operands(ws)
    return [Target(w) for w in (ops if any(w.text.startswith("--reference") for w in ws) else ops[1:])]


def base(word: Word) -> str:
    """The base name of the path a word names.

    Args:
        word: a word naming a path.

    Returns:
        Its last part, without a trailing slash.
    """
    return os.path.basename(word.text.replace("\\", "/").rstrip("/"))


def into_last(values: str = "", moves: bool = False, flag: str = "-") -> Writes:
    """cp, mv, copy: the last operand is the destination (a folder holds the files of the same name).

    Args:
        values: its options followed by a value, separated by spaces.
        moves: True for a move: the sources are written (taken away) too.
        flag: what an option starts with ("-", or "/" for cmd).

    Returns:
        ws -> the Targets (the destination with the sources' names); it raises Unseen for -t or no destination.
    """
    def targets(ws: Sequence[Word]) -> list[Target]:
        if any(w.text in ("-t", "--target-directory") or w.text.startswith("--target-directory=") for w in ws):
            raise Unseen("a destination given by -t")
        ops = operands(ws, values.split(), flag)
        if len(ops) < 2:
            raise Unseen("a copy or a move with no destination")
        sources = ops[:-1]
        return [Target(w) for w in sources if moves] + [Target(ops[-1], tuple(base(w) for w in sources))]
    return targets


def ln(ws: Sequence[Word]) -> list[Target]:
    """The writes of ln: the link made (the last operand, or the base name of the one operand in the folder).

    Args:
        ws: the words after the command's name.

    Returns:
        The Target of the link (a folder destination with the sources' names).

    Raises:
        Unseen: a destination given by -t.
    """
    if any(w.text == "-t" or w.text.startswith("--target-directory") for w in ws):
        raise Unseen("a destination given by -t")
    ops = operands(ws, ("-S", "--suffix"))
    if len(ops) == 1:
        return [Target(Word(base(ops[0])))]
    return [Target(ops[-1], tuple(base(w) for w in ops[:-1]))] if ops else []


def sed(ws: Sequence[Word]) -> list[Target]:
    """The writes of sed: its files when it edits in place (-i), else none.

    Args:
        ws: the words after the command's name.

    Returns:
        A Target for each file edited in place; [] without -i.

    Raises:
        Unseen: an in-place flag it does not follow, or a script that writes a file or runs a command (w, e).
    """
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


def curl(ws: Sequence[Word]) -> list[Target]:
    """The writes of curl: the files of -o and --output.

    Args:
        ws: the words after the command's name.

    Returns:
        A Target for each output file.

    Raises:
        Unseen: an option that writes a file it does not name (-O, -J, -D, -c, -K...), or -o with no file.
    """
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


def wget(ws: Sequence[Word]) -> list[Target]:
    """The writes of wget: the files of -O, -o, -a and their long forms (- for stdout left out).

    Args:
        ws: the words after the command's name.

    Returns:
        A Target for each file named.

    Raises:
        Unseen: -P, no file named by -O (the address names it), or -O with no file.
    """
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


def dd(ws: Sequence[Word]) -> list[Target]:
    """The writes of dd: the file of of=.

    Args:
        ws: the words after the command's name.

    Returns:
        A Target for each of= word.
    """
    return [Target(Word(w.text[3:], w.dynamic)) for w in ws if w.text.startswith("of=")]


def tar(ws: Sequence[Word]) -> list[Target]:
    """The writes of tar: none for a listing (-t, --list).

    Args:
        ws: the words after the command's name.

    Returns:
        [] for a listing.

    Raises:
        Unseen: tar makes or unpacks files it does not name.
    """
    first = ws[0].text if ws else ""
    listing = first in ("-t", "--list") or (not first.startswith("--") and "t" in first and not set(first) & set("xcru"))
    if not listing:
        raise Unseen("tar makes or unpacks files the reader does not name")
    return []


def find(ws: Sequence[Word]) -> list[Target]:
    """The writes of find: none, unless an action deletes, runs or writes (FIND_ACTIONS).

    Args:
        ws: the words after the command's name.

    Returns:
        [].

    Raises:
        Unseen: find deletes, runs a command or writes a file.
    """
    if any(w.text in FIND_ACTIONS for w in ws):
        raise Unseen("find deletes, runs a command or writes a file")
    return []


def option_value(ws: Sequence[Word], names: Sequence[str]) -> list[Target]:
    """The file an option names (sort -o, tree -o), as a separate word or joined to it.

    Args:
        ws: the words after the command's name.
        names: the option's spellings.

    Returns:
        [the Target of the first such option's value], or [] when none is given.
    """
    for i, w in enumerate(ws):
        for name in names:
            if w.text == name and i + 1 < len(ws):
                return [Target(ws[i + 1])]
            if w.text.startswith(name) and len(w.text) > len(name) and (name.startswith("--") or len(name) == 2):
                return [Target(Word(w.text[len(name):].lstrip("="), w.dynamic))]
    return []


def inline(name: str, code: Word) -> list[Target]:
    """The writes of inline code an interpreter runs: none, when nothing in it may write or run a command.

    Args:
        name: the interpreter's name.
        code: the code's word (or its heredoc as a Word).

    Returns:
        [].

    Raises:
        Unseen: the code is dynamic or holds a call of WRITE_API.
    """
    if code.dynamic or WRITE_API.search(code.text):
        raise Unseen(f"the code {name} runs may write files or run commands")
    return []


def interpreter(name: str, flags: Sequence[str]) -> Callable[[Sequence[Word], Optional[str]], list[Target]]:
    """The writes of an interpreter of INTERPRETERS: only inline code (-c, -e...) or a heredoc program is read.

    Args:
        name: the interpreter's name (python, node, perl...).
        flags: its options that take inline code.

    Returns:
        (ws, heredoc) -> [] when the code writes nothing; it raises Unseen for a script, a module, perl -i, or code
        that may write.
    """
    def targets(ws: Sequence[Word], heredoc: Optional[str]) -> list[Target]:
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
