"""The desk of a plan: a plan {title, files, tests} is checked and normalized before it is kept. Its root is the
folder the MCP server runs in, the project's folder."""
import os
import re

PLAN_KEYS = ("title", "files", "tests")
ABSOLUTE = re.compile(r"^([A-Za-z]:|[\\/])")


def paths(value, name, required):
    if not isinstance(value, list) or not all(isinstance(p, str) and p.strip() for p in value) or (required and not value):
        raise ValueError(f"{name} is a list of paths" + (", at least one" if required else ""))
    for p in value:
        parts = [s.lower() for s in re.split(r"[\\/]", p)]
        if ABSOLUTE.match(p) or ".." in parts:
            raise ValueError(f"{name}: {p} is not a path inside the repository (relative, no ..)")
        if ".git" in parts:
            raise ValueError(f"{name}: {p} is inside .git, which no plan edits")
        if any(mark in p for mark in "~%,"):
            raise ValueError(f"{name}: {p} holds ~, % or a comma, which the shell or the form would read otherwise")
    return [p.replace("\\", "/") for p in value]


def checked(plan):
    if not isinstance(plan, dict) or set(plan) - set(PLAN_KEYS):
        raise ValueError(f"a plan holds only {', '.join(PLAN_KEYS)}")
    if not isinstance(plan.get("title"), str) or not plan["title"].strip() or '"' in plan["title"]:
        raise ValueError("a plan has a title, without double quotes (the form question quotes it)")
    return {"title": plan["title"].strip(), "files": paths(plan.get("files"), "files", True),
            "tests": paths(plan.get("tests", []), "tests", False),
            "root": os.getcwd().replace("\\", "/")}  # the MCP server runs in the project's folder
