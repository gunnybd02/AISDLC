"""Loader: reads the ITEMS of the hooks, mcp and gear blocks without importing them, and resolves an item's ref to its object.
An index (a block's __init__.py) only declares: a docstring and one literal `ITEMS = [{kind, name, ref}, ...]`.
The actions of mcp are read from their own files (mcp/actions/*.py): each holds one literal
ACTIONS = [("block.name", "Class"), ...] naming classes it defines (a block is only a name prefix, and a file may hold
several); action_files() reads them without importing, actions() imports one file's.
This is the one module allowed to import dynamically (imports_net)."""
import ast
import importlib
import re
from dataclasses import dataclass
from pathlib import Path

KINDS = {"hooks": ("hook", "translator"), "mcp": ("server", "tool", "source", "table"),
         "gear": ("translator", "detector", "rule")}
FIELDS = ("kind", "name", "ref")
NAME = re.compile(r"^[a-z][a-z0-9_]*$")
ACTIONS_DIR = ("harness", "mcp", "actions")
NOT_ACTIONS = ("__init__.py", "table.py")
ACTION = re.compile(r"^([a-z][a-z0-9_]*)\.([a-z][a-z0-9_-]*)$")


@dataclass(frozen=True)
class ActionFile:
    module: str
    entries: tuple  # ((block, name, class name), ...)


@dataclass(frozen=True)
class Item:
    block: str
    kind: str
    name: str
    ref: str


class LoaderError(Exception):
    def __init__(self, problems):
        super().__init__("\n".join(problems))
        self.problems = problems


class Loader:
    def __init__(self, claude_dir):
        self.root = Path(claude_dir)

    def problems(self):
        return self.read()[1] + self.read_actions()[1]

    def action_files(self):
        files, problems = self.read_actions()
        if problems:
            raise LoaderError(problems)
        return files

    @staticmethod
    def actions(action_file):
        """(block, name, class) of each entry of the file."""
        module = importlib.import_module(action_file.module)
        return [(block, name, getattr(module, cls)) for block, name, cls in action_file.entries]

    def read_actions(self):
        files, problems, seen = [], [], {}
        folder = self.root.joinpath(*ACTIONS_DIR)
        for path in sorted(folder.glob("*.py")) if folder.is_dir() else []:
            if path.name in NOT_ACTIONS:
                continue
            rel = path.relative_to(self.root).as_posix()
            found, why = Loader.action_file(path, rel)
            if why:
                problems.append(f"{rel}: {why}")
                continue
            twice = [f"{b}.{n}" for b, n, _ in found.entries if (b, n) in seen]
            if twice:
                problems.append(f"{rel}: {', '.join(twice)} declared already (in {seen[tuple(twice[0].split('.', 1))]})")
                continue
            seen.update({(b, n): rel for b, n, _ in found.entries})
            files.append(found)
        return files, problems

    @staticmethod
    def action_file(path, rel):
        """What an action file declares, read from its syntax tree, or why it does not declare it."""
        try:
            body = ast.parse(path.read_text(encoding="utf-8-sig")).body
        except (SyntaxError, UnicodeDecodeError, ValueError) as e:
            return None, f"does not parse ({type(e).__name__})"
        lists = [n.value for n in body if isinstance(n, ast.Assign) and len(n.targets) == 1
                 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "ACTIONS"]
        only = 'an action file holds one literal ACTIONS = [("block.name", "Class"), ...]'
        if len(lists) != 1:
            return None, only
        try:
            listed = ast.literal_eval(lists[0])
        except (ValueError, TypeError, SyntaxError, RecursionError):
            return None, only
        if not (isinstance(listed, list) and listed and all(
                isinstance(e, tuple) and len(e) == 2 and all(isinstance(x, str) for x in e) for e in listed)):
            return None, only
        classes = {n.name for n in body if isinstance(n, ast.ClassDef)}
        entries = []
        for full, cls in listed:
            m = ACTION.match(full)
            if not m:
                return None, f"{full} is not block.name (lower case letters, digits, _; - in a name)"
            if cls not in classes:
                return None, f"ACTIONS names {cls}, which the file does not define"
            entries.append((m.group(1), m.group(2), cls))
        return ActionFile(rel[:-3].replace("/", "."), tuple(entries)), ""

    def items(self):
        items, problems = self.read()
        if problems:
            raise LoaderError(problems)
        return items

    @staticmethod
    def resolve(item):
        module, _, attr = item.ref.partition(":")
        return getattr(importlib.import_module(module), attr)

    def read(self):
        items, problems, seen = [], [], {}
        for block, kinds in KINDS.items():
            rel = f"harness/{block}/__init__.py"
            path = self.root / rel
            if not path.is_file():
                problems.append(f"{rel}: missing; every block has an index")
                continue
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError as e:
                problems.append(f"{rel}: does not decode as UTF-8 ({e.reason})")
                continue
            entries, why = Loader.entries_of(text)
            if why:
                problems.append(f"{rel}: {why}")
                continue
            for n, entry in enumerate(entries, 1):
                item, why = self.item_of(block, kinds, entry)
                if why:
                    problems.append(f"{rel} item {n}: {why}")
                elif item.name in seen:
                    problems.append(f"{rel}: '{item.name}' is declared twice (also in {seen[item.name]})")
                else:
                    seen[item.name] = block
                    items.append(item)
        return items, problems

    @staticmethod
    def entries_of(text):
        """The literal list of ITEMS, or why the index is not only a declaration."""
        only = "an index only declares: a docstring and one literal ITEMS = [...]"
        try:
            body = ast.parse(text).body
        except SyntaxError as e:
            return [], f"does not parse ({e.msg}, line {e.lineno})"
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        if len(body) != 1 or not isinstance(body[0], ast.Assign) or [ast.unparse(t) for t in body[0].targets] != ["ITEMS"]:
            return [], only
        try:
            entries = ast.literal_eval(body[0].value)
        except (ValueError, TypeError, RecursionError):
            return [], only
        if not isinstance(entries, list):
            return [], only
        return entries, ""

    def item_of(self, block, kinds, entry):
        if not isinstance(entry, dict) or sorted(entry) != sorted(FIELDS) or not all(isinstance(v, str) for v in entry.values()):
            return None, f"fields are exactly {', '.join(FIELDS)}, each a string"
        item = Item(block, entry["kind"], entry["name"], entry["ref"])
        if item.kind not in kinds:
            return None, f"kind '{item.kind}' is not held by block {block} (it holds: {', '.join(kinds)})"
        if not NAME.match(item.name):
            return None, f"name '{item.name}' is lower case letters, digits and _"
        return (item, "") if self.ref_ok(block, item.ref) else \
            (None, f"ref '{item.ref}' is not harness.{block}.<module>:<Name> of a file of the block")

    def ref_ok(self, block, ref):
        m = re.match(rf"^harness\.{block}\.([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*):[A-Za-z_]\w*$", ref)
        return bool(m) and (self.root / "harness" / block / (m.group(1).replace(".", "/") + ".py")).is_file()
