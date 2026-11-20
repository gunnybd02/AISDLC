"""Farewell: say bye to a person by name."""


def farewell(name):
    """Return "Bye, <name>". Raise ValueError if the name is empty."""
    if not name:
        raise ValueError("name must not be empty")
    return f"Bye, {name}"
