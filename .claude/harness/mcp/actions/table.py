"""ActionTable: the actions `run` can reach, by block and name. A block is only the prefix of an action's name; the
actions come from the ACTIONS literals of mcp/actions/*.py (the loader reads them), each a McpAction class
(utils/contracts.py). args_problem checks the arguments of a call against the action's args_schema before it runs."""
TYPES = {"string": str, "object": dict, "boolean": bool, "integer": int, "number": (int, float), "array": list}


def fields(action):
    """(argument name, type, required) of each property of the action's args_schema."""
    schema = action.args_schema
    required = set(schema.get("required", ()))
    return [(n, p.get("type", "string"), n in required) for n, p in schema.get("properties", {}).items()]


def signature(action):
    return f"{action.name}(" + ", ".join(f"{n}{'' if req else '?'}: {t}" for n, t, req in fields(action)) + ")"


def args_problem(action, given):
    """Why the arguments do not fit the action, or "": an object, every required one there, each of its type, no other."""
    if not isinstance(given, dict):
        return "the arguments are an object"
    spec = {n: (t, req) for n, t, req in fields(action)}
    for n, (t, req) in spec.items():
        if n not in given:
            if req:
                return f"{signature(action)}: {n} is missing"
        elif (isinstance(given[n], bool) and t != "boolean") or not isinstance(given[n], TYPES[t]):
            return f"{signature(action)}: {n} is a {t}"
    extra = sorted(set(given) - set(spec))
    return f"{signature(action)}: no argument {', '.join(extra)}" if extra else ""


class ActionTable:
    def __init__(self):
        self.entries = {}  # (block, name) -> McpAction class

    def add(self, action):
        key = (action.block, action.name)
        if key in self.entries:
            raise ValueError(f"{action.block}.{action.name} is added already")
        unknown = [t for _, t, _ in fields(action) if t not in TYPES]
        if unknown:
            raise ValueError(f"{action.block}.{action.name}: unknown argument types {unknown}")
        self.entries[key] = action

    @property
    def blocks(self):
        return sorted({b for b, _ in self.entries})

    def about(self, block):
        """What a block does: the summaries of its actions."""
        return "; ".join(a.summary for a in self.actions(block))

    def actions(self, block):
        return [a for (b, _), a in sorted(self.entries.items()) if b == block]

    def action(self, block, name):
        return self.entries[(block, name)]
