"""Put a mark on both sides of a text."""


def wrap(text, mark):
    """Return text with mark on both sides; an empty mark raises ValueError."""
    if not mark:
        raise ValueError("mark must not be empty")
    return f"{mark}{text}{mark}"
