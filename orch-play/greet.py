"""A polite greeting."""


def greet(name):
    """Return a polite greeting for name; an empty name raises ValueError."""
    if not name:
        raise ValueError("name must not be empty")
    return f"Good day, {name}."
