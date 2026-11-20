"""Greeting helper for the greet child (issue #108)."""

GREETING = "Hi"


def greet(name):
    """Return a greeting for name, e.g. greet("Ann") -> "Hi, Ann".

    Raises ValueError when name is empty.
    """
    if not name:
        raise ValueError("name must not be empty")
    return f"{GREETING}, {name}"
