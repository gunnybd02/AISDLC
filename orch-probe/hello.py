"""Greet a person by name."""


def hello(name: str) -> str:
    """Return a greeting for ``name``; an empty name raises ValueError."""
    if not name:
        raise ValueError("name must not be empty")
    return f"Hello, {name}"
