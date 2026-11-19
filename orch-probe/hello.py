"""Greet a person by name.

AC1: hello("Ann") returns "Hello, Ann".
AC2: hello("") raises ValueError.
"""


def hello(name):
    """Return "Hello, <name>"; an empty name is a ValueError."""
    if not name:
        raise ValueError("name must not be empty")
    return f"Hello, {name}"
