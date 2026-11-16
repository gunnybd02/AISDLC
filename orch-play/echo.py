"""Repeat a text."""


def echo(text, times):
    """Return text repeated times times; times below one raises ValueError."""
    if times < 1:
        raise ValueError("times must be at least one")
    return text * times
