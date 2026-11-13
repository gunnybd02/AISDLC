"""Loader: reads the ITEMS of the hooks, mcp and gear blocks without importing them, and resolves an item's ref to its object.
An index (a block's __init__.py) only declares: a docstring and one literal `ITEMS = [{kind, name, ref}, ...]`.
The actions of mcp are read from their own files (mcp/actions/*.py): each says BLOCK, ABOUT and ACTIONS = [Class, ...],
the classes it defines; action_files() reads them without importing, actions() imports one.
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
DECLARES = ("BLOCK", "ABOUT", "ACTIONS")


@dataclass(frozen=True)
class ActionFile:
    module: str
    block: str
    about: str
    names: tuple


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
        module = importlib.import_module(action_file.module)
        return [getattr(module, name) for name in action_file.names]

    def read_actions(self):
        files, problems, blocks = [], [], {}
        folder = self.root.joinpath(*ACTIONS_DIR)
        for path in sorted(folder.glob("*.py")) if folder.is_dir() else []:
            if path.name in NOT_ACTIONS:
                continue
            rel = path.relative_to(self.root).as_posix()
            found, why = Loader.action_file(path, rel)
            if why:
                problems.append(f"{rel}: {why}")
            elif found.block in blocks:
                problems.append(f"{rel}: block {found.block} is declared by {blocks[found.block]} already")
            else:
                blocks[found.block] = rel
                files.append(found)
        return files, problems

    @staticmethod
    def action_file(path, rel):
        """What an action file declares, read from its syntax tree, or why it does not declare it."""
        try:
            body = ast.parse(path.read_text(encoding="utf-8-sig")).body
        except (SyntaxError, UnicodeDecodeError, ValueError) as e:
            return None, f"does not parse ({type(e).__name__})"
        values = {}
        for node in body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                    and node.targets[0].id in DECLARES:
                values[node.targets[0].id] = node.value
        classes = {n.name for n in body if isinstance(n, ast.ClassDef)}
        if sorted(values) != sorted(DECLARES):
            return None, f"an action file declares {', '.join(DECLARES)} at its top level"
        block, about, listed = values["BLOCK"], values["ABOUT"], values["ACTIONS"]
        if not (isinstance(block, ast.Constant) and isinstance(block.value, str) and NAME.match(block.value)):
            return None, "BLOCK is a literal name: lower case letters, digits and _"
        if not (isinstance(about, ast.Constant) and isinstance(about.value, str) and about.value.strip()):
            return None, "ABOUT is a literal sentence"
        if not (isinstance(listed, ast.List) and listed.elts and all(isinstance(e, ast.Name) for e in listed.elts)):
            return None, "ACTIONS is a literal list of the action classes of the file"
        names = tuple(e.id for e in listed.elts)
        missing = [n for n in names if n not in classes]
        if missing:
            return None, f"ACTIONS names {', '.join(missing)}, which the file does not define"
        module = rel[:-3].replace("/", ".")
        return ActionFile(module, block.value, about.value, names), ""

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
