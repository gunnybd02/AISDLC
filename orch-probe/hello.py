"""Greet a person by name."""


def hello(name):
    """Return "Hello, <name>"; an empty name raises ValueError."""
    if not name:
        raise ValueError("name must not be empty")
    return f"Hello, {name}"
