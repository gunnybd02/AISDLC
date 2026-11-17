"""Trim a text."""


def trim(text):
    """Return text without the spaces at both ends; a value that is not a string raises TypeError."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return text.strip(" ")
