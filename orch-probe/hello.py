"""Greet a person by name."""


def hello(name):
    if not name:
        raise ValueError("name must not be empty")
    return f"Hello, {name}"
