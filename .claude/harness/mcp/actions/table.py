"""ActionTable: the blocks `run` can reach and their typed actions. An action declares its arguments as
{"name": type, "optional?": type}; a call with a missing, extra or mistyped argument is refused before the handler."""
from dataclasses import dataclass
from typing import Callable

TYPES = {"string": str, "object": dict, "boolean": bool, "number": (int, float), "array": list}


@dataclass(frozen=True)
class Action:
    name: str
    about: str
    args: dict
    handler: Callable

    def spec(self):
        """(argument name, type, required) for each declared argument."""
        return [(k.rstrip("?"), t, not k.endswith("?")) for k, t in self.args.items()]

    def signature(self):
        return f"{self.name}(" + ", ".join(f"{n}{'' if req else '?'}: {t}" for n, t, req in self.spec()) + ")"

    def problem(self, given):
        if not isinstance(given, dict):
            return "the arguments are an object"
        spec = {n: (t, req) for n, t, req in self.spec()}
        for n, (t, req) in spec.items():
            if n not in given:
                if req:
                    return f"{self.signature()}: {n} is missing"
            elif (isinstance(given[n], bool) and t != "boolean") or not isinstance(given[n], TYPES[t]):
                return f"{self.signature()}: {n} is a {t}"
        extra = sorted(set(given) - set(spec))
        return f"{self.signature()}: no argument {', '.join(extra)}" if extra else ""


class ActionTable:
    def __init__(self):
        self.blocks = {}  # block name -> (about, {action name: Action})

    def add_block(self, block, about):
        if block in self.blocks:
            raise ValueError(f"block {block} is added already")
        self.blocks[block] = (about, {})

    def add(self, block, name, about, args, handler):
        if block not in self.blocks:
            raise KeyError(f"no block {block}")
        if name in self.blocks[block][1]:
            raise ValueError(f"{block}.{name} is added already")
        unknown = [t for t in args.values() if t not in TYPES]
        if unknown:
            raise ValueError(f"{block}.{name}: unknown argument types {unknown}")
        self.blocks[block][1][name] = Action(name, about, dict(args), handler)

    def about(self, block):
        return self.blocks[block][0]

    def actions(self, block):
        return list(self.blocks[block][1].values())

    def action(self, block, name):
        return self.blocks[block][1][name]
