"""Greet a person by name."""


def hello(name):
    """Return a greeting for name; an empty name is refused with ValueError."""
    if not name:
        raise ValueError("name must not be empty")
    return f"Hello, {name}"
