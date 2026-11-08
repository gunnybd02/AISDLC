"""Loader: reads the ITEMS of the mcp and gear blocks without importing them, and resolves an item's ref to its object.
An index (a block's __init__.py) only declares: a docstring and one literal `ITEMS = [{kind, name, ref}, ...]`.
This is the one module allowed to import dynamically (imports_net)."""
import ast
import importlib
import re
from dataclasses import dataclass
from pathlib import Path

KINDS = {"mcp": ("hook", "server", "tool", "source", "table"), "gear": ("translator", "detector", "rule")}
FIELDS = ("kind", "name", "ref")
NAME = re.compile(r"^[a-z][a-z0-9_]*$")


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
        return self.read()[1]

    def items(self):
        items, problems = self.read()
        if problems:
            raise LoaderError(problems)
        return items

    def registry(self):
        """{name: the object its ref names}, for every item of every block."""
        return {item.name: self.resolve(item) for item in self.items()}

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
            entries, why = Loader.entries_of(path.read_text(encoding="utf-8"))
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
        except ValueError:
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
