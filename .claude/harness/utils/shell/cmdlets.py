"""The PowerShell commands the shell reader knows: the cmdlets that only read (PS_READS), the aliases of the cmdlets
(PS_ALIASES), and the cmdlets that write (CMDLETS), each described by its parameters (Cmdlet) so cmdlet() can name the
paths it writes. place_ops.py looks a PowerShell command up here."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from harness.utils.shell.paths import Target, Unseen
from harness.utils.shell.command import Word
from harness.utils.shell.write_ops import base

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


@dataclass(frozen=True)
class Cmdlet:
    """The parameters of a cmdlet that writes, as cmdlet() reads them."""
    positional: tuple[str, ...] = ()  # what each word with no parameter name is: path (written), source (read), value
    paths: tuple[str, ...] = ()  # parameters whose value is a written path
    sources: tuple[str, ...] = ()  # parameters whose value is read
    values: tuple[str, ...] = ()  # other parameters with a value
    switches: tuple[str, ...] = ()
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


def cmdlet(name: str, spec: Cmdlet, ws: Sequence[Word]) -> list[Target]:
    """The places a cmdlet of CMDLETS writes.

    Args:
        name: the cmdlet's name, lower case, aliases resolved.
        spec: its parameters.
        ws: the words after its name.

    Returns:
        A Target for each written path (with the sources' names when it copies into a folder).

    Raises:
        Unseen: an unknown parameter, a parameter with no value, a word it cannot place, or items from the pipeline.
    """
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
